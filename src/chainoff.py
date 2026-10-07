from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

import common
import settings_store as ss

NONCE_MAX = 10
NONCE_MAX_AGE = 2 * 86400
BIG_USD = 100.0
UNSUPPORTED = {"bsc": "BSC 는 따로 도는 수집기(tj-bsc)라 이 버튼으로는 아직 못 꺼요",
               "sol": "Solana 는 따로 도는 수집기(tj-sol)라 이 버튼으로는 아직 못 꺼요"}
UNITS = ["tj-evm", "tj-core", "tj-web"]
MANUAL = "pm2 restart " + " ".join(UNITS)
KEY_RE = re.compile(r"^[a-z0-9_]{1,24}$")
BACKUP_KEEP = 20
SENT_DAYS = 30
SPARK_N = 15
BAL_FN = None
_SENT_CACHE = {"at": 0.0, "db": None, "v": None}
_SENT_TTL = 300.0
_SENT_LOCK = threading.Lock()

_NAMES = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism", "polygon": "Polygon", "scroll": "Scroll",
          "zksync": "zkSync", "gnosis": "Gnosis", "robinhood": "Robinhood", "arc": "Arc", "bsc": "BSC", "sol": "Solana"}


def _names() -> dict:
    t = dict(_NAMES)
    common.fill_chain_table(t)
    return t


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _evm_addr(a) -> str:
    s = str(a or "").lower()
    return s if s.startswith("0x") and len(s) == 42 else ""


def _sent_by_chain(now: float):
    db = common.DB_PATH
    with _SENT_LOCK:
        c9 = _SENT_CACHE
        if c9["db"] == db and c9["v"] is not None and now - c9["at"] < _SENT_TTL:
            return c9["v"]
    if not os.path.exists(db):
        return None
    since = int(now - SENT_DAYS * 86400)
    out = {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        try:
            rows = conn.execute("SELECT location, source_id, MIN(event_ts) FROM postings WHERE leg_kind='gas' AND source_kind='chain_tx'"
                                " AND event_ts>=? GROUP BY location, source_id", (since,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    seen = set()
    for loc, sid, ts in rows:
        parts = str(loc or "").split(":")
        if len(parts) < 2 or parts[0] != "wallet":
            continue
        ch = parts[1]
        if (ch, sid) in seen:
            continue
        seen.add((ch, sid))
        e = out.setdefault(ch, {"n": 0, "spark": [0] * SPARK_N})
        e["n"] += 1
        try:
            i = int((float(ts) - since) // (SENT_DAYS * 86400 / SPARK_N))
        except (TypeError, ValueError):
            continue
        e["spark"][min(SPARK_N - 1, max(0, i))] += 1
    with _SENT_LOCK:
        _SENT_CACHE.update(at=now, db=db, v=out)
    return out


def _chain_wallets(raw: dict, cfg: dict, gate: dict) -> dict:
    by = {}
    for w in (cfg.get("wallets") or []):
        if not isinstance(w, dict):
            continue
        t = w.get("type", "evm")
        if t == "sol":
            a = str(w.get("address") or "")
            if a:
                by.setdefault("sol", set()).add(a)
            continue
        a = _evm_addr(w.get("address"))
        if a:
            by.setdefault("bsc" if t == "bsc_rpc" else str(w.get("chain") or ""), set()).add(a)
    off = [k for k in (cfg.get("_disabled_chains") or [])]
    if off:
        reg = {_evm_addr(w.get("address")) for w in raw.get("wallets") or [] if isinstance(w, dict) and w.get("type", "evm") in ("evm", "bsc_rpc")}
        reg.discard("")
        for w in raw.get("wallets") or []:
            if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain") in off:
                a = _evm_addr(w.get("address"))
                if a:
                    by.setdefault(w["chain"], set()).add(a)
        for key, ent in ((gate.get("pairs") or {}) if isinstance(gate.get("pairs"), dict) else {}).items():
            if not isinstance(ent, dict) or not ent.get("active") or ":" not in key:
                continue
            c, a = key.split(":", 1)
            if c in off and a.lower() in reg:
                by.setdefault(c, set()).add(a.lower())
    by.pop("", None)
    return by


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _nonce_of(chain: str, addr: str, gate: dict, tier_pairs: dict, now: float = None):
    now = time.time() if now is None else now
    if chain == "sol":
        return None
    tp = tier_pairs.get(addr) if isinstance(tier_pairs, dict) else None
    if not isinstance(tp, dict) or tp.get("code") != "eoa":
        return None
    ch = (gate.get("chains") or {}).get(chain) if isinstance(gate.get("chains"), dict) else None
    if not isinstance(ch, dict) or ch.get("ok") is not True:
        return None
    at = _int(ch.get("checkedAt"))
    if at is None or at != _int(gate.get("updatedAt")) or not 0 <= now - at <= NONCE_MAX_AGE:
        return None
    pr = gate.get("pairs") if isinstance(gate.get("pairs"), dict) else {}
    e = pr.get(f"{chain}:{addr}")
    if isinstance(e, dict):
        n = _int(e.get("nonce"))
        return n if n is not None and n >= 0 and _int(e.get("lastChecked")) == at else None
    return 0 if addr in set(ch.get("addrs") or []) else None


def _tier_book(chain: str) -> dict:
    d = _read(os.path.join(common.STATE_DIR, f"addr_tier_{chain}.json"), {})
    return d if d.get("scope") == chain and isinstance(d.get("pairs"), dict) else {}


def _status_of(book: dict, n_wallets: int):
    sm = book.get("summary") if isinstance(book.get("summary"), dict) else None
    if not sm:
        return None
    if int(sm.get("filling") or 0) > 0:
        return "filling"
    if n_wallets and int(sm.get("empty") or 0) >= n_wallets:
        return "empty"
    return "ok"


def _calls_of(book: dict, cfg: dict):
    sm = book.get("summary") if isinstance(book.get("summary"), dict) else None
    if not sm:
        return None
    try:
        import addr_tier
        s9 = dict(sm, lp=bool(book.get("path") == "etherscan"))
        est = addr_tier.estimate([s9], cfg)
        return {"perDay": int(sum(float(v.get("perDay") or 0) for v in est.values())),
                "es": int(float((est.get("etherscan") or {}).get("perDay") or 0))}
    except Exception:
        return None


def _poll_sec(chain: str, cfg: dict, raw: dict, book: dict):
    sm = book.get("summary") if isinstance(book.get("summary"), dict) else {}
    poll9 = sm.get("period") or sm.get("basePoll")
    if poll9:
        try:
            return int(float(poll9))
        except (TypeError, ValueError):
            pass
    try:
        if chain == "sol":
            return int(float((raw.get("sol") or {}).get("poll_sec") or 60))
        if chain == "bsc":
            return int(float((raw.get("bsc") or {}).get("poll_sec") or 60))
        import addr_tier
        return int(addr_tier.chain_poll(cfg if chain in (cfg.get("chains") or {}) else raw, chain))
    except Exception:
        return None


def _bal() -> dict | None:
    fn = BAL_FN
    if not callable(fn):
        return None
    try:
        v = fn()
        return {str(k): float(x) for k, x in v.items() if x is not None} if isinstance(v, dict) else None
    except Exception:
        return None


RPC_ONLY_WHY = "이 체인은 노드에서 직접 읽어서 오래 끄면 빠진 기간을 다시 못 받을 수 있어요"
LAST_EVM_WHY = "마지막 남은 EVM 체인이라 끄면 EVM 수집기가 멈춰요(재시작 반복) — 다른 EVM 체인이 켜져 있을 때만 끌 수 있어요"
FIRST_SCAN_WHY = "첫 수집 중인 지갑이 있어요 — 끝나면 끌 수 있어요(지금 끄면 다시 켤 때 빠진 기간을 이어 받지 못할 수 있어요)"
BOOK_STALE_SEC = 1800


def _first_scan_missing(chain: str, wallets, book: dict = None, now: float = None) -> bool:
    if not wallets:
        return False
    now = time.time() if now is None else now
    book = book if isinstance(book, dict) else {}
    pairs = book.get("pairs") if isinstance(book.get("pairs"), dict) else None
    upd = book.get("updatedAt")
    if pairs is None or not isinstance(upd, (int, float)) or now - float(upd) > BOOK_STALE_SEC:
        return True
    plow = {str(k).lower(): v for k, v in pairs.items()}
    cur = _read(os.path.join(common.STATE_DIR, f"cursor_evm_{chain}.json"), {})
    low = {str(k).lower(): v for k, v in cur.items()}
    job = low.get("_bfjob") if isinstance(low.get("_bfjob"), dict) else {}
    job_ws = {str(x).lower() for x in (job.get("wallets") or [])}
    for a in wallets:
        a = str(a).lower()
        p = plow.get(a)
        if not isinstance(p, dict):
            return True
        hold = str(p.get("hold") or "")
        if hold == "boot" or hold.startswith("hist:") or p.get("fill"):
            return True
        anc = _int(low.get(a))
        if anc is None or anc < 0:
            return True
        if any(k + a in low for k in ("_bfes:", "_disc:", "_bf:")) or a in job_ws:
            return True
    return False


def _evm_chains_on(cfg: dict) -> set:
    return {str(w.get("chain")) for w in cfg.get("wallets") or [] if isinstance(w, dict) and w.get("type", "evm") == "evm" and w.get("chain")}


def _off_reason(chain: str, cc, evm_on: set, runner: bool, wallets=(), book: dict = None) -> str:
    if chain in UNSUPPORTED:
        return UNSUPPORTED[chain]
    if isinstance(cc, dict) and common.chain_discovery(chain, cc) == "rpc":
        return RPC_ONLY_WHY
    if not runner and evm_on and evm_on <= {chain}:
        return LAST_EVM_WHY
    if _first_scan_missing(chain, wallets, book):
        return FIRST_SCAN_WHY
    return ""


def summary(now: float = None) -> dict:
    now = time.time() if now is None else now
    raw = ss.read_config_raw()
    try:
        cfg = ss.load_config_quiet()
    except Exception:
        cfg = raw
    gate = _read(common.ACTIVITY_GATE_PATH, {})
    names = _names()
    rch = raw.get("chains") if isinstance(raw.get("chains"), dict) else {}
    lch = cfg.get("chains") if isinstance(cfg.get("chains"), dict) else {}
    keys = []
    for k, cc in list(rch.items()) + list(lch.items()):
        if isinstance(cc, dict) and not str(k).startswith("_") and KEY_RE.match(str(k)) and k not in keys:
            keys.append(k)
    by = _chain_wallets(raw, cfg, gate)
    if isinstance(raw.get("bsc"), dict) and by.get("bsc"):
        keys.append("bsc")
    if by.get("sol"):
        keys.append("sol")
    sent = _sent_by_chain(now)
    bal = _bal()
    ap = apply_info()
    evm_on = _evm_chains_on(cfg)
    rows = []
    for k in keys:
        rc = rch.get(k) if isinstance(rch.get(k), dict) else None
        on = k in lch or k in ("bsc", "sol")
        if rc is not None and not common.chain_enabled(k, rc):
            on = False
        ws = sorted(by.get(k) or ())
        book = _tier_book(k)
        tp = book.get("pairs") or {}
        nonces = [_nonce_of(k, a, gate, tp, now) for a in ws]
        known = [n for n in nonces if n is not None]
        unknown = len(nonces) - len(known)
        sm = book.get("summary") if isinstance(book.get("summary"), dict) else {}
        tiers = sm.get("tiers") if isinstance(sm.get("tiers"), list) else None
        mark = (rc or {}).get("_chainoff") if isinstance((rc or {}).get("_chainoff"), dict) else {}
        usd = None if bal is None else round(float(bal.get(k) or 0.0), 2)
        why = _off_reason(k, lch.get(k), evm_on, ap["evmRunner"], ws, book) if on else ""
        can = not why
        se = (sent or {}).get(k) if sent is not None else None
        holds = sm.get("holds") if isinstance(sm.get("holds"), dict) else {}
        rec = bool(on and can and ws and unknown == 0 and known and max(known) <= NONCE_MAX
                   and sent is not None and sm and not int(sm.get("filling") or 0) and not any(int(holds.get(h) or 0) for h in ("boot", "hist"))
                   and not int((se or {}).get("n") or 0))
        rows.append({
            "key": k, "name": names.get(k, k), "on": on, "can": can, "why": why,
            "lock": None if can else ("sep" if k in UNSUPPORTED else "rpc" if why == RPC_ONLY_WHY else "boot" if why == FIRST_SCAN_WHY else "last"),
            "auto": bool(isinstance(lch.get(k), dict) and lch[k].get("_auto")) or bool(mark.get("created")),
            "wallets": len(ws), "nonces": nonces, "maxNonce": max(known) if known else None, "unknown": unknown,
            "status": "off" if not on else _status_of(book, len(ws)),
            "fill": int(sm.get("filling") or 0) if sm else None, "rest": (sum(int(x or 0) for x in tiers[1:]) if tiers else None),
            "pollSec": _poll_sec(k, cfg, raw, book) if on else None,
            "calls": _calls_of(book, cfg) if on else None,
            "sent30": None if sent is None else int((se or {}).get("n") or 0),
            "spark": None if sent is None else list((se or {}).get("spark") or [0] * SPARK_N),
            "usd": usd, "big": bool(usd is not None and usd >= BIG_USD),
            "offAt": int(mark["at"]) if not on and isinstance(mark.get("at"), (int, float)) else None,
            "recommend": rec,
        })
    on_rows = [r for r in rows if r["on"]]
    rec_rows = [r for r in rows if r["recommend"]]
    all_w = set()
    for k in keys:
        all_w |= set(by.get(k) or ())
    tot_calls = [r["calls"]["perDay"] for r in on_rows if r.get("calls")]
    sw = gate.get("updatedAt")
    return {"ok": True, "at": int(now), "rows": rows, "nOn": len(on_rows), "nOff": len(rows) - len(on_rows), "nRec": len(rec_rows),
            "nWallets": len(all_w), "nonceMax": NONCE_MAX, "bigUsd": BIG_USD, "sweptAt": int(sw) if isinstance(sw, (int, float)) else None,
            "callsDay": sum(tot_calls) if tot_calls else None,
            "recCallsDay": sum(r["calls"]["perDay"] for r in rec_rows if r.get("calls")) if rec_rows and all(r.get("calls") for r in rec_rows) else None,
            "pollSteps": None,
            "apply": ap}


def _backup(raw_bytes: bytes, now: float) -> str:
    d = os.path.join(common.STATE_DIR, "backups", "config_chainoff")
    os.makedirs(d, exist_ok=True)
    for i in range(100):
        p = os.path.join(d, f"config.json.{int(now)}_{time.time_ns() % 10**9:09d}_{i}")
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise OSError("백업 파일 이름을 만들지 못했어요")
    with os.fdopen(fd, "wb") as f:
        f.write(raw_bytes)
        f.flush()
        os.fsync(f.fileno())
    try:
        olds = sorted((x for x in os.listdir(d) if x.startswith("config.json.")), key=lambda x: os.path.getmtime(os.path.join(d, x)))
        for x in olds[:-BACKUP_KEEP]:
            os.unlink(os.path.join(d, x))
    except OSError:
        pass
    return p


def _ign_has(ign: list, chain: str) -> bool:
    return any(str(x).lower() == chain for x in ign)


def set_enabled(chain, on, now: float = None) -> dict:
    now = time.time() if now is None else now
    if not isinstance(chain, str) or not KEY_RE.match(chain):
        raise ValueError("체인 이름 형식이 아닙니다")
    if not isinstance(on, bool):
        raise ValueError("on 은 true/false 만 됩니다")
    if chain in UNSUPPORTED:
        raise ValueError(UNSUPPORTED[chain])
    with ss.LOCK:
        with open(common.CONFIG_PATH, "rb") as f:
            raw_bytes = f.read()
        raw = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config.json 형식 오류")
        chains = raw.setdefault("chains", {})
        if not isinstance(chains, dict):
            raise ValueError("config.json chains 형식 오류")
        known = {r["key"]: r for r in summary(now)["rows"]}
        if chain not in known:
            raise ValueError("설정에 없는 체인입니다")
        cc = chains.get(chain)
        cur_on = not (isinstance(cc, dict) and not common.chain_enabled(chain, cc))
        if cur_on == on:
            return {"ok": True, "chain": chain, "on": on, "changed": False, "apply": apply_info()}
        if not on and not known[chain]["can"]:
            raise ValueError(known[chain]["why"] or "이 체인은 여기서 끌 수 없어요")
        sw = raw.get("chain_sweep")
        if sw is not None and not isinstance(sw, dict):
            raise ValueError("config.json chain_sweep 형식 오류")
        ign = list((sw or {}).get("ignore") or [])
        if not on:
            mark = {"at": int(now)}
            if isinstance(cc, dict):
                mark["had"] = "enabled" in cc
                cc["enabled"] = False
                cc["_chainoff"] = mark
            else:
                mark["created"] = True
                chains[chain] = {"enabled": False, "_chainoff": mark}
            if not _ign_has(ign, chain):
                ign.append(chain)
                mark["ign"] = True
        else:
            mark = cc.get("_chainoff") if isinstance(cc.get("_chainoff"), dict) else {}
            legacy = not mark.get("created") and common.auto_off_block(cc)
            if legacy:
                trial = dict(raw, chains={k: v for k, v in chains.items() if k != chain})
                ok9 = (sw or {}).get("auto_enable") is True and any(d["chain"] == chain and d["ok"] and d.get("block")
                                                                    for d in common.gate_decisions(trial))
                if not ok9:
                    raise ValueError("이 체인은 설정 블록이 비어 있어 여기서 켜면 수집기가 멈춰요 — config.json 의 체인 설정을 먼저 채워 주세요")
            if mark.get("created") or legacy:
                chains.pop(chain, None)
            else:
                cc.pop("_chainoff", None)
                if mark and not mark.get("had") and common.chain_enabled(chain, {}):
                    cc.pop("enabled", None)
                else:
                    cc["enabled"] = True
            if mark.get("ign"):
                ign = [x for x in ign if str(x).lower() != chain]
        if sw is not None or ign:
            raw["chain_sweep"] = dict(sw or {}, ignore=ign)
        bk = _backup(raw_bytes, now)
        ss.write_config_raw(raw)
    return {"ok": True, "chain": chain, "on": on, "changed": True, "apply": request_apply(chain, on), "backup": os.path.basename(bk)}


def apply_info() -> dict:
    try:
        rs = ss.runner_status() or {}
        own = {u: h for u, h in rs.items() if isinstance(h, dict) and h.get("by") != "reload"}
        reload_on = any(isinstance(h, dict) and h.get("by") == "reload" for h in rs.values())
        evm_runner = "evm" in own
        mode = "runner" if own else ("reload" if reload_on else "")
    except Exception:
        mode, evm_runner = "", False
    return {"runner": bool(mode), "mode": mode, "evmRunner": evm_runner, "manual": MANUAL, "units": list(UNITS)}


def request_apply(chain: str, on: bool) -> dict:
    try:
        import wallet_register as wr
        wr._record_reload({"ts": int(time.time()), "chains": [str(chain)], "on": bool(on), "source": "chainoff", "units": list(UNITS)})
    except Exception:
        pass
    return apply_info()
