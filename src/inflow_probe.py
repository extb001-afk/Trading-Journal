from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.parse

import common

log = logging.getLogger("tj-inflow")

DEFAULT_SEC = 600
FAIL_RETRY_SEC = 180
TICK_SEC = 20.0
CALL_TIMEOUT = 10
MAX_CHUNKS = 8
WAKE_MAX = 10
ANKR_ADDR_MAX = 1000
PUB_ADDR_MAX = 500
PUB_SPAN = 2000
SPAN_MIN = 10
ADDR_MIN = 16
COOL_DENY = 6 * 3600
COOL_ERR = 120
SPAM_TTL = 3600
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
T1155_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
T1155_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"
ANKR_NET = {"eth": "eth", "arbitrum": "arbitrum", "polygon": "polygon", "gnosis": "gnosis", "story": "story_mainnet", "somnia": "somnia_mainnet",
            "avalanche": "avalanche", "base": "base", "bsc": "bsc", "kaia": "kaia", "monad": "monad_mainnet",
            "optimism": "optimism", "zksync": "zksync_era", "scroll": "scroll", "linea": "linea", "blast": "blast"}
RPC_IMPL = None
_MEM = {}
_LOCK = threading.Lock()
_SPAM = {}


def settings(cfg: dict) -> dict:
    raw = ((cfg or {}).get("addr_tier") or {}) if isinstance((cfg or {}).get("addr_tier"), dict) else {}
    v = raw.get("inflow_sec", DEFAULT_SEC)
    try:
        s = int(float(v))
    except (TypeError, ValueError, OverflowError):
        s = DEFAULT_SEC
    if isinstance(v, bool):
        s = DEFAULT_SEC
    return {"sec": 0 if s <= 0 else min(max(s, 60), 86400)}


def state_path(chain: str) -> str:
    return os.path.join(common.STATE_DIR, f"inflow_{chain}.json")


def _mem(chain: str) -> dict:
    with _LOCK:
        m = _MEM.get(chain)
        if m is None:
            st = common.read_json(state_path(chain), {})
            st = st if isinstance(st, dict) else {}
            if not isinstance(st.get("blk"), int) or isinstance(st.get("blk"), bool) or st["blk"] < 0:
                st.pop("blk", None)
            if not isinstance(st.get("carry"), dict):
                st["carry"] = {}
            m = _MEM[chain] = {"st": st, "cool": {}, "span": {}, "addr": {}, "cid": {}}
        return m


def _save(chain: str, st: dict):
    try:
        common.atomic_write_json(state_path(chain), st)
    except OSError as e:
        log.warning("%s 받음 탐지 상태 저장 실패(다음 바퀴): %s", chain, e)


def _ankr_key():
    try:
        import nodekeys
        return nodekeys._key(nodekeys._env(), nodekeys.ENV_ANKR)
    except Exception:
        return None


def _is_key_node(u: str) -> bool:
    try:
        import nodekeys
        return bool(nodekeys.is_key_node(u))
    except Exception:
        h = (urllib.parse.urlsplit(str(u)).hostname or "").lower()
        return h.endswith(".g.alchemy.com") or h == "rpc.ankr.com" or h.endswith(".quiknode.pro") or "nodereal" in h


def _ankr_span() -> int:
    try:
        import nodekeys
        return int(nodekeys.SPAN.get("ankr") or 3000)
    except Exception:
        return 3000


def nodes(cfg: dict, chain: str, key: str = None) -> list:
    out = []
    if key and ANKR_NET.get(chain):
        out.append(("ankr", f"https://rpc.ankr.com/{ANKR_NET[chain]}/{key}", _ankr_span(), ANKR_ADDR_MAX, "Ankr"))
    try:
        import evm_watch
        rn = evm_watch.rpc_nodes(cfg, chain)
    except Exception as e:
        log.debug("%s 받음 탐지 노드 표 못 읽음: %s", chain, e)
        cc = ((cfg or {}).get("chains") or {}).get(chain) or {}
        rn = {"logs": list(cc.get("rpc_logs") or cc.get("rpcs") or []), "caps": {}, "fallback": {}, "addr_max": 0}
    caps = rn.get("caps") or {}
    fb = rn.get("fallback") or {}
    am = int(rn.get("addr_max") or 0)
    pub = [u for u in dict.fromkeys(rn.get("logs") or []) if isinstance(u, str) and u.startswith("http") and not _is_key_node(u)]
    pub.sort(key=lambda u: 1 if u in fb else 0)
    for u in pub:
        out.append(("pub", u, int(caps.get(u) or PUB_SPAN), min(PUB_ADDR_MAX, am) if am else PUB_ADDR_MAX,
                    (urllib.parse.urlsplit(u).hostname or "?").lower()))
    if am and out and out[0][0] == "ankr":
        out[0] = out[0][:3] + (min(ANKR_ADDR_MAX, am),) + out[0][4:]
    return out


def _call(url: str, method: str, params: list, deadline: float):
    if RPC_IMPL is not None:
        return RPC_IMPL(url, method, params)
    import bf_engine
    left = deadline - time.time()
    if left <= 0:
        raise TimeoutError("받음 탐지 바퀴 시간 상한")
    to = min(float(CALL_TIMEOUT), left)
    with bf_engine.ledger_burst(False):
        return bf_engine.rpc_call(url, method, params, timeout=to, retries=1, prio="fg", deadline=deadline, sem_timeout=to)


def _expect_cid(cfg: dict, chain: str):
    cc = ((cfg or {}).get("chains") or {}).get(chain) or {}
    v = cc.get("chain_id")
    if v is None:
        try:
            import chaincatalog
            v = (chaincatalog.CATALOG.get(chain) or {}).get("chain_id")
        except Exception:
            v = None
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _hexint(v) -> int:
    if isinstance(v, str):
        return int(v, 16) if v.lower().startswith("0x") else int(v)
    return int(v)


def _pad(w: str) -> str:
    return "0x" + w[2:].lower().rjust(64, "0")


def _addr_of_topic(t) -> str:
    t = str(t or "").lower()
    return "0x" + t[-40:] if t.startswith("0x") and len(t) == 66 else ""


def _safe(e, key=None) -> str:
    m = common.redact_urls(str(e))
    if key:
        m = m.replace(key, "<키>")
    return m[:120]


def _err_kind(e) -> str:
    m = str(e).lower()
    code = getattr(e, "code", None)
    if getattr(e, "kind", None) == "budget":
        return "busy"
    if code in (401, 403, -32052) or re.search(r"http(?: error)?\s*40[13]\b", m) or any(k in m for k in ("-32052", "not allowed", "unauthorized", "forbidden")):
        return "deny"
    if "topic" in m and ("exceed" in m or "too many" in m or "max" in m):
        return "topics"
    if any(k in m for k in ("block range", "range", "too large", "-32005", "limit exceeded", "query returned more than", "-32602", "timeout", "timed out", "408")):
        return "range"
    return "err"


def _token_spam(chain: str, ca: str, now: float) -> bool:
    k = (chain, ca)
    c = _SPAM.get(k)
    if c and now - c[0] < SPAM_TTL:
        return c[1]
    spam = False
    try:
        import spamguard
        if not spamguard.is_genuine(chain, ca):
            sym = None
            if os.path.exists(common.DB_PATH):
                conn = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=1)
                try:
                    r = conn.execute("SELECT symbol FROM assets WHERE kind='token' AND chain=? AND address=?", (chain, ca)).fetchone()
                finally:
                    conn.close()
                sym = r[0] if r else None
            if sym:
                lure = getattr(spamguard, "_TAIL_LURE", None)
                spam = bool(spamguard.impostor_of(sym) or spamguard.odd_symbol(sym) or (lure is not None and lure.search(str(sym))))
    except Exception as e:
        log.debug("%s %s 스팸 판정 못 함(깨움 쪽): %s", chain, ca[:10], e)
        spam = False
    if len(_SPAM) > 5000:
        _SPAM.clear()
    _SPAM[k] = (now, spam)
    return spam


def _targets(tb, now: float) -> dict:
    out = {}
    for w in list(tb.wallets):
        try:
            _t, iv, why = tb.tier(w, now)
        except Exception:
            continue
        if not why and iv > 0:
            out[str(w).lower()] = w
    return out


class Deadline(Exception):
    pass


def _scan_range(url, frm, to, groups, deadline, res, prog: dict, on_row):
    for gi, g in enumerate(groups):
        for ti, topics in enumerate(([TRANSFER, None, g], [[T1155_SINGLE, T1155_BATCH], None, None, g])):
            pos = gi * 2 + ti
            if pos < int(prog.get("next") or 0):
                continue
            if time.time() >= deadline:
                raise Deadline("받음 탐지 바퀴 시간 상한 — 다음 바퀴에 이어서")
            res["calls"] += 1
            rows = _call(url, "eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": topics}], deadline)
            if not isinstance(rows, list):
                raise RuntimeError(f"getLogs 비정상 result: {type(rows).__name__}(빈 배열 아님)")
            for r in rows:
                if isinstance(r, dict):
                    on_row(r)
            prog["next"] = pos + 1


def _shape(groups) -> str:
    return hashlib.sha256(json.dumps(groups, separators=(",", ":")).encode()).hexdigest()[:16]


def tick(cfg: dict, wt, now: float = None, deadline: float = None):
    try:
        return _tick(cfg, wt, now, deadline)
    except Exception as e:
        log.warning("%s 받음 탐지 실패(다음 바퀴): %s", getattr(wt, "chain", "?"), _safe(e, _ankr_key()))
        return None


def _tick(cfg, wt, now, deadline):
    tb = getattr(wt, "_tier", None)
    if tb is None or not getattr(tb, "active", False) or getattr(tb, "path_kind", None) not in ("etherscan", "blockscout"):
        return None
    sec = settings(cfg)["sec"]
    if sec <= 0:
        return None
    chain = wt.chain
    now = time.time() if now is None else now
    m = _mem(chain)
    st = m["st"]
    last_try = float(st.get("try") or 0)
    wait = sec if st.get("ok", True) else min(sec, FAIL_RETRY_SEC)
    if last_try > now:
        last_try = 0.0
    if now - last_try < wait:
        return None
    deadline = deadline or (time.time() + TICK_SEC)
    st["try"] = int(now)
    st["sec"] = sec
    tg = _targets(tb, now)
    res = {"chain": chain, "targets": len(tg), "calls": 0, "logs": 0, "woke": 0, "ext": 0, "carry": 0, "spam": 0, "zero": 0, "done_by": 0}
    if not tg:
        st.update(ok=True, at=int(now), targets=0, node=None, err=None, woke=0, logs=0)
        st["carry"] = {}
        _save(chain, st)
        _health(chain, st)
        return res
    pairs = tb.pairs
    min_full = min(int((pairs.get(k) or {}).get("fullBlk") or 0) for k in tg.values())
    allw = sorted({str(w).lower() for w in tb.wallets})
    conf = int(getattr(wt, "conf_depth", 0) or 0)
    key = _ankr_key()
    found = {}
    node_used, err_last, ok = None, None, False
    cur = st.get("blk")
    nl = nodes(cfg, chain, key)
    amax = max(1, min([int(m["addr"].get(u) or a0) for _k, u, _s, a0, _l in nl] or [PUB_ADDR_MAX]))
    groups = [[_pad(w) for w in allw[i:i + amax]] for i in range(0, len(allw), amax)]
    shape = _shape(groups)
    for kind, url, span0, amax0, label in nl:
        if time.time() > deadline:
            break
        if m["cool"].get(url, 0) > now:
            continue
        span = int(m["span"].get(url) or span0)
        try:
            if url not in m["cid"]:
                exp = _expect_cid(cfg, chain)
                if exp is not None:
                    res["calls"] += 1
                    got = _hexint(_call(url, "eth_chainId", [], deadline))
                    if got != exp:
                        m["cool"][url] = now + COOL_DENY
                        err_last = f"{label}: 체인 ID 다름({got} ≠ {exp})"
                        log.error("★%s 받음 탐지 노드 %s 체인 ID 다름(%s ≠ %s) — 이 프로세스에서 건너뜀★", chain, label, got, exp)
                        continue
                m["cid"][url] = True
            res["calls"] += 1
            safe = _hexint(_call(url, "eth_blockNumber", [], deadline)) - conf
        except Exception as e:
            if time.time() >= deadline:
                err_last = f"{label}: 시간 상한 — 다음 바퀴에 이어서"
                break
            k9 = _err_kind(e)
            if k9 != "busy":
                m["cool"][url] = now + (COOL_DENY if k9 == "deny" else COOL_ERR)
            err_last = f"{label}: {_safe(e, key)}"
            continue
        base_lo = max(min_full + 1, (cur + 1) if isinstance(cur, int) else 0)
        sc9 = st.get("scan") if isinstance(st.get("scan"), dict) else None
        resume = bool(sc9 and sc9.get("shape") == shape and all(type(sc9.get(k)) is int for k in ("from", "to", "next"))
                      and base_lo <= sc9["from"] <= safe and sc9["from"] <= sc9["to"] and 0 < sc9["next"] < 2 * len(groups))
        budget = span * MAX_CHUNKS
        if resume:
            lo = sc9["from"]
        else:
            lo = base_lo
            if safe - lo + 1 > budget:
                lo = safe - budget + 1
        skip9 = (lo - base_lo) if (lo > base_lo and (isinstance(cur, int) or min_full > 0)) else 0
        if lo > safe:
            if isinstance(cur, int) and safe < cur:
                err_last = f"{label}: 노드가 뒤처짐(head − 확정 깊이 {safe} < 확인한 블록 {cur})"
                continue
            ok, node_used = True, label
            break
        a = lo
        failed = False
        while a <= safe and time.time() <= deadline:
            first9 = resume and a == sc9["from"]
            b = min(sc9["to"], safe, a + span - 1) if first9 else min(safe, a + span - 1)
            n0 = sc9["next"] if first9 else 0
            prog = {"next": n0}
            try:
                _scan_range(url, a, b, groups, deadline, res, prog, lambda r, b=b: _take(chain, r, tg, found, res, b, now))
            except Exception as e:
                if int(prog.get("next") or 0) > n0:
                    st["scan"] = {"from": a, "to": b, "next": int(prog["next"]), "shape": shape}
                failed = True
                if isinstance(e, Deadline) or time.time() >= deadline:
                    err_last = f"{label}: 시간 상한 — 다음 바퀴에 이어서({int(prog.get('next') or 0)}/{2 * len(groups)})"
                    break
                k9 = _err_kind(e)
                if k9 == "topics" and amax > ADDR_MIN:
                    m["addr"][url] = max(ADDR_MIN, amax // 2)
                elif k9 == "range" and span > SPAN_MIN:
                    m["span"][url] = max(SPAN_MIN, span // 2)
                elif k9 != "busy":
                    m["cool"][url] = now + (COOL_DENY if k9 == "deny" else COOL_ERR)
                err_last = f"{label}: {_safe(e, key)}"
                break
            st.pop("scan", None)
            resume = False
            if skip9:
                if now - float(st.get("skipAt") or 0) >= 3600:
                    log.info("%s 받음 탐지 구간이 커서 최신 %d블록만 — 앞 %d블록은 받침 복구 몫", chain, budget, skip9)
                st["skipped"] = int(st.get("skipped") or 0) + skip9
                st["skipAt"] = int(now)
                skip9 = 0
            cur = b
            node_used = label
            a = b + 1
        if not failed and cur is not None and cur >= safe:
            ok = True
            break
    if isinstance(cur, int):
        st["blk"] = int(cur)
    res["woke"], res["ext"], res["carry"], res["done_by"] = _wake(tb, tg, found, st, now)
    day = int(now // 86400)
    cd = st.get("callsDay") if isinstance(st.get("callsDay"), dict) and st["callsDay"].get("day") == day else {"day": day, "n": 0, "woke": 0}
    cd["n"] = int(cd.get("n") or 0) + res["calls"]
    cd["woke"] = int(cd.get("woke") or 0) + res["woke"]
    st.pop("calls", None)
    st.update(ok=bool(ok), node=node_used, err=None if ok else (err_last or "노드 없음·시간 상한"), targets=len(tg),
              logs=res["logs"], woke=res["woke"], callsDay=cd)
    if ok:
        st["at"] = int(now)
    if res["woke"] or res["ext"]:
        tb.save(force=True)
    _save(chain, st)
    _health(chain, st)
    if res["woke"] or res["ext"]:
        log.info("%s 받음 탐지: 쉬는 쌍 %d개 깨움(토큰 받음)%s — 이번 바퀴 탐색기로 복구", chain, res["woke"],
                 f" · 깨운 블록 늘림 {res['ext']}" if res["ext"] else "")
    return res


def _take(chain, r, tg, found, res, end_blk, now):
    if r.get("removed"):
        return
    topics = r.get("topics") or []
    if not topics:
        return
    t0 = str(topics[0]).lower()
    if t0 == TRANSFER and len(topics) >= 3:
        to = _addr_of_topic(topics[2])
        if len(topics) == 3:
            try:
                if int(str(r.get("data") or "0x0"), 16) == 0:
                    if to in tg:
                        res["zero"] += 1
                    return
            except ValueError:
                pass
    elif t0 in (T1155_SINGLE, T1155_BATCH) and len(topics) >= 4:
        to = _addr_of_topic(topics[3])
    else:
        return
    if to not in tg:
        return
    res["logs"] += 1
    ca = str(r.get("address") or "").lower()
    if re.fullmatch(r"0x[0-9a-f]{40}", ca) and _token_spam(chain, ca, now):
        res["spam"] += 1
        return
    try:
        blk = _hexint(r.get("blockNumber"))
    except (TypeError, ValueError):
        blk = int(end_blk)
    found[to] = max(blk, found.get(to, 0))


def _wake(tb, tg, found, st, now) -> tuple:
    carry = {}
    for w, b in (st.get("carry") or {}).items():
        if isinstance(b, int) and not isinstance(b, bool) and w in tg:
            carry[w] = b
    for w, b in found.items():
        carry[w] = max(b, carry.get(w, 0))
    woke = ext = done_by = 0
    left = {}
    for w, b in sorted(carry.items(), key=lambda kv: kv[1]):
        k = tg.get(w)
        if k is None:
            continue
        with tb.lock:
            p = tb.pairs.get(k) or {}
            if int(p.get("fullBlk") or 0) >= b:
                done_by += 1
                continue
            wk = p.get("wake")
            if isinstance(wk, dict):
                if wk.get("blk") is not None and int(wk["blk"]) < b:
                    wk["blk"] = int(b)
                    tb._dirty = True
                    ext += 1
                continue
        if woke >= WAKE_MAX:
            left[w] = b
            continue
        tb.wake(k, b, "token_in")
        woke += 1
    st["carry"] = left
    return woke, ext, len(left), done_by


def _health(chain: str, st: dict):
    try:
        import bf_engine
        bf_engine.health("evm").facts(chain, inflow={"at": st.get("at"), "try": st.get("try"), "ok": bool(st.get("ok")), "node": st.get("node"),
                                                     "n": st.get("targets"), "sec": st.get("sec")})
    except Exception:
        pass


def health_text(f, now: float = None) -> str:
    if not isinstance(f, dict) or not f.get("n"):
        return ""
    now = time.time() if now is None else now
    at = f.get("at")
    node = str(f.get("node") or "")[:40]
    if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0:
        s = f"쉬는 지갑 토큰 받음 확인 {_ago(now - float(at))}" + (f"({node})" if node else "")
    else:
        s = "쉬는 지갑 토큰 받음 확인 아직 못 함"
    if not f.get("ok"):
        s += " · 직전 확인 실패 — 곧 다시"
    return s


def _ago(sec: float) -> str:
    sec = max(0.0, float(sec))
    if sec < 90:
        return "방금"
    if sec < 3600:
        return f"{int(sec // 60)}분 전"
    if sec < 86400:
        return f"{int(sec // 3600)}시간 전"
    return f"{int(sec // 86400)}일 전"


def web_view(cfg: dict = None, now: float = None) -> dict:
    import glob
    now = time.time() if now is None else now
    rows = []
    chains9 = ((cfg or {}).get("chains") or {}) if isinstance(cfg, dict) else {}
    for f in sorted(glob.glob(os.path.join(common.STATE_DIR, "inflow_*.json"))):
        d = common.read_json(f, {})
        if not isinstance(d, dict):
            continue
        c = os.path.basename(f)[len("inflow_"):-len(".json")]
        if chains9 and c not in chains9:
            continue
        rows.append({"c": c, "at": d.get("at"), "try": d.get("try"), "ok": bool(d.get("ok", True)), "node": d.get("node"),
                     "n": int(d.get("targets") or 0), "woke": int(d.get("woke") or 0), "stale": now - float(d.get("try") or 0) > 3 * max(60, int(d.get("sec") or DEFAULT_SEC))})
    return {"sec": settings(cfg or {})["sec"], "rows": rows}
