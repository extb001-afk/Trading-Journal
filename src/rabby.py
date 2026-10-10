"""Wallet portfolio reference reader."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import common

API = "https://api.rabby.io"
STATE_NAME = "rabby_portfolio.json"
DAILY_NAME = "rabby_daily.json"
ZERO = "0x0000000000000000000000000000000000000000"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

BOT_CHAIN_IDS = {"eth": 1, "base": 8453, "arbitrum": 42161, "optimism": 10, "polygon": 137, "scroll": 534352,
                 "zksync": 324, "gnosis": 100, "robinhood": 4663, "bsc": 56, "arc": 5042,
                 "monad": 143, "megaeth": 4326, "plasma": 9745, "xlayer": 196, "stable": 988, "hyperevm": 999, "sonic": 146,
                 "unichain": 130, "linea": 59144, "blast": 81457, "mantle": 5000, "berachain": 80094, "sei": 1329,
                 "abstract": 2741, "ink": 57073, "soneium": 1868, "worldchain": 480, "celo": 42220, "mode": 34443,
                 "taiko": 167000, "polygon_zkevm": 1101, "fantom": 250, "avalanche": 43114, "kaia": 8217, "bob": 60808,
                 "fraxtal": 252, "cronos": 25, "manta": 169, "metis": 1088, "lisk": 1135, "opbnb": 204, "katana": 747474,
                 "zora": 7777777, "ronin": 2020, "apechain": 33139, "story": 1514, "gravity": 1625, "chiliz": 88888}
RABBY_CHAIN_IDS = {"eth": 1, "bsc": 56, "arb": 42161, "op": 10, "base": 8453, "matic": 137, "scrl": 534352, "era": 324,
                   "xdai": 100, "avax": 43114, "linea": 59144, "blast": 81457, "mnt": 5000, "ftm": 250, "sonic": 146,
                   "uni": 130, "bera": 80094, "celo": 42220, "zora": 7777777, "mode": 34443, "taiko": 167000,
                   "abs": 2741, "world": 480, "sei": 1329, "hyper": 999, "plasma": 9745, "monad": 143, "ink": 57073,
                   "soneium": 1868, "xlayer": 196, "klay": 8217, "bob": 60808, "frax": 252, "cro": 25, "manta": 169,
                   "metis": 1088, "lisk": 1135, "opbnb": 204, "nova": 42170, "pze": 1101, "katana": 747474,
                   "megaeth": 4326, "stable": 988, "gravity": 1625, "chiliz": 88888, "story": 1514, "cfx": 1030,
                   "merlin": 4200, "ape": 33139}
DEF = {"enabled": True, "wallet_every_h": 24.0, "gap_sec": 75.0, "backoff_sec": 1800.0, "backoff_max_sec": 21600.0,
       "first_delay_sec": 300.0, "tick_sec": 600.0, "timeout_sec": 40.0, "min_usd": 0.01, "daily_calls_max": 150,
       "min_wallet_usd": 1000.0}


class RateLimited(OSError):
    pass


def settings(cfg: dict) -> dict:
    s = dict(DEF)
    for k, v in ((cfg or {}).get("rabby") or {}).items():
        if k in DEF:
            try:
                s[k] = type(DEF[k])(v)
            except (TypeError, ValueError):
                pass
    return s


def evm_wallets(cfg: dict, include_disabled: bool = False) -> list:
    out = set()
    for w in list((cfg or {}).get("wallets") or []) + (list((cfg or {}).get("_disabled_wallets") or []) if include_disabled else []):
        if not isinstance(w, dict) or w.get("type") == "sol" or w.get("chain") == "sol":
            continue
        a = str(w.get("address") or "").strip().lower()
        if a.startswith("0x") and len(a) == 42:
            out.add(a)
    return sorted(out)


def wallet_chains(cfg: dict) -> set:
    out = set()
    for w in list((cfg or {}).get("wallets") or []) + list((cfg or {}).get("_disabled_wallets") or []):
        if isinstance(w, dict) and w.get("chain") and w.get("type") != "sol":
            out.add((str(w.get("address") or "").lower(), str(w["chain"])))
    return out


def bot_chain_ids(cfg: dict) -> dict:
    m = {v: k for k, v in BOT_CHAIN_IDS.items()}
    for k, c in ((cfg or {}).get("chains") or {}).items():
        if not isinstance(c, dict):
            continue
        for f in ("chain_id", "etherscan_chainid"):
            try:
                if c.get(f):
                    m[int(c[f])] = k
                    break
            except (TypeError, ValueError):
                pass
    return m


def chain_resolver(cfg: dict, state: dict):
    ids = dict(RABBY_CHAIN_IDS)
    for rid, cid in ((state or {}).get("chainIds") or {}).items():
        try:
            ids[str(rid)] = int(cid)
        except (TypeError, ValueError):
            pass
    bmap = bot_chain_ids(cfg)
    known = set(((cfg or {}).get("chains") or {}).keys()) | {"bsc"}
    known |= {str(w.get("chain")) for w in (cfg or {}).get("wallets") or [] if isinstance(w, dict) and w.get("chain")}
    known |= set((cfg or {}).get("_disabled_chains") or [])

    def res(rid):
        rid = str(rid or "")
        cid = ids.get(rid)
        if cid is not None and cid in bmap and bmap[cid] in known:
            return bmap[cid]
        return rid if rid in known else None
    return res


def chain_label(state: dict, rid: str, bot_names: dict = None) -> str:
    nm = ((state or {}).get("chainNames") or {}).get(rid)
    return str(nm or (bot_names or {}).get(rid) or rid)


def http_get(url: str, timeout: float = 40.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(common.read_capped(r))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(f"429 {url.split('?')[0]}")
        raise


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and abs(v) != float("inf") else 0.0


def _tok(t: dict) -> dict:
    sym = t.get("optimized_symbol") or t.get("display_symbol") or t.get("symbol") or "?"
    out = {"id": str(t.get("id") or ""), "chain": str(t.get("chain") or ""), "sym": str(sym)[:32],
           "amt": _num(t.get("amount")), "px": _num(t.get("price"))}
    for k, s in (("is_verified", "v"), ("is_core", "c"), ("is_scam", "scam"), ("is_suspicious", "sus")):
        if t.get(k) is not None:
            out[s] = bool(t.get(k))
    return out


def trim_tokens(lst) -> list:
    return [_tok(t) for t in (lst or []) if isinstance(t, dict) and _num(t.get("amount")) != 0]


def trim_protocols(pl) -> list:
    out = []
    for p in pl or []:
        if not isinstance(p, dict):
            continue
        items = []
        for it in p.get("portfolio_item_list") or []:
            if not isinstance(it, dict):
                continue
            det = it.get("detail") if isinstance(it.get("detail"), dict) else {}
            assets, debts = [], []
            lists = [det.get(k) for k in ("supply_token_list", "reward_token_list", "token_list") if isinstance(det.get(k), list)]
            for k in ("token", "position_token", "margin_token"):
                if isinstance(det.get(k), dict):
                    lists.append([det[k]])
            if lists or isinstance(det.get("borrow_token_list"), list):
                for L in lists:
                    assets += [_tok(t) for t in L if isinstance(t, dict) and _num(t.get("amount")) > 0]
                debts = [_tok(t) for t in (det.get("borrow_token_list") or []) if isinstance(t, dict) and _num(t.get("amount")) > 0]
            else:
                for t in it.get("asset_token_list") or []:
                    if not isinstance(t, dict):
                        continue
                    a = _num(t.get("amount"))
                    if a > 0:
                        assets.append(_tok(t))
                    elif a < 0:
                        d = _tok(t)
                        d["amt"] = -a
                        debts.append(d)
            st = it.get("stats") if isinstance(it.get("stats"), dict) else {}
            pool = it.get("pool") if isinstance(it.get("pool"), dict) else {}
            items.append({"name": str(it.get("name") or "")[:40], "types": [str(x) for x in (it.get("detail_types") or [])][:4],
                          "idx": str(it.get("position_index") or "")[:80], "pool": str(pool.get("id") or "").lower(),
                          "ctrl": str(pool.get("controller") or "").lower(), "adapter": str(pool.get("adapter_id") or "")[:60],
                          "assets": assets, "debts": debts,
                          "a": _num(st.get("asset_usd_value")), "d": _num(st.get("debt_usd_value"))})
        if items:
            out.append({"proto": str(p.get("id") or "")[:60], "pname": str(p.get("name") or p.get("id") or "")[:40],
                        "chain": str(p.get("chain") or ""), "items": items})
    return out


def fetch_wallet(addr: str, get=None, sleep=time.sleep, gap: float = 75.0, timeout: float = 40.0, want_protocols=None) -> dict:
    get = get or (lambda u: http_get(u, timeout))
    total = get(f"{API}/v1/user/total_balance?id={addr}")
    if not isinstance(total, dict):
        raise ValueError("Rabby 응답 형식이 예상과 다름")
    chains = []
    for c in total.get("chain_list") or []:
        if isinstance(c, dict) and c.get("id"):
            chains.append({"id": str(c["id"]), "cid": c.get("community_id"), "name": str(c.get("name") or c["id"])[:40],
                           "usd": _num(c.get("usd_value"))})
    tot = _num(total.get("total_usd_value"))
    prots = []
    if want_protocols is None or want_protocols(tot):
        sleep(gap)
        pl = get(f"{API}/v1/user/complex_protocol_list?id={addr}")
        if not isinstance(pl, list):
            raise ValueError("Rabby 응답 형식이 예상과 다름")
        prots = trim_protocols(pl)
    return {"total": tot, "chains": chains, "tokens": [], "protocols": prots}


def need_protocols(prev: dict, bot_usd, total: float, *, now: float = None) -> bool:
    if not isinstance(prev, dict) or not prev.get("fetchedAt") or prev.get("protocols"):
        return True
    try:
        if (time.time() if now is None else float(now)) - float(prev["fetchedAt"]) >= RB_EVERY_SAME:
            return True
    except (TypeError, ValueError):
        return True
    try:
        b = float(bot_usd)
    except (TypeError, ValueError):
        return True
    return abs(float(total) - b) > max(200.0, 0.05 * max(float(total), b, 0.0))


BOTUSD_NAME = "rabby_bot_usd.json"


def load_bot_usd(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("w"), dict):
        return None
    out = {}
    for a, v in d["w"].items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f and abs(f) != float("inf") and isinstance(a, str) and a.startswith("0x"):
            out[a.lower()] = f
    return out


def watch_addrs(state: dict, addrs: list, bot_usd, min_usd: float) -> list:
    if not min_usd or min_usd <= 0:
        return list(addrs)
    ws = (state or {}).get("wallets") or {}
    bu = bot_usd if isinstance(bot_usd, dict) else {}
    out = []
    for a in addrs:
        try:
            v = max(float(bu.get(a) or 0), float((ws.get(a) or {}).get("total") or 0))
        except (TypeError, ValueError):
            v = 0.0
        if v >= min_usd:
            out.append(a)
    return out


def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: str, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


RB_EVERY_SAME = 7 * 86400
RB_EVERY_EMPTY = 30 * 86400
RB_EMPTY_USD = 1.0


def wallet_every(w: dict, bot_usd, every_sec: float) -> float:
    if not isinstance(w, dict) or not w.get("fetchedAt"):
        return 0.0
    if w.get("protocols"):
        return every_sec
    try:
        rb = float(w.get("total") or 0)
        bu = float(bot_usd or 0)
    except (TypeError, ValueError):
        return every_sec
    if rb < RB_EMPTY_USD and bu < RB_EMPTY_USD:
        return max(every_sec, RB_EVERY_EMPTY)
    return max(every_sec, RB_EVERY_SAME)


def due_wallet(state: dict, addrs: list, now: float, every_sec: float, bot_usd: dict = None):
    ws = (state or {}).get("wallets") or {}
    bot_usd = bot_usd if isinstance(bot_usd, dict) else {}
    best, best_k = None, None
    for a in addrs:
        w = ws.get(a) or {}
        t = float(w.get("fetchedAt") or 0)
        tt = float(w.get("triedAt") or 0)
        ev = wallet_every(w, bot_usd.get(a), every_sec)
        if now - t < ev or now - tt < min(every_sec, 3 * 3600):
            continue
        try:
            v = float(bot_usd[a]) if a in bot_usd else float(w.get("total") or 0)
        except (TypeError, ValueError):
            v = 0.0
        k = (-v, t)
        if best is None or k < best_k:
            best, best_k = a, k
    return best


def _freeze_disabled(cfg: dict, state: dict, old: dict, fresh: dict) -> dict:
    off = set((cfg or {}).get("_disabled_chains") or ())
    off.update(c for c, cc in ((cfg or {}).get("chains") or {}).items() if isinstance(cc, dict) and not common.chain_enabled(c, cc))
    if not off:
        return fresh
    ids = dict((state or {}).get("chainIds") or {})
    for c in fresh.get("chains") or []:
        if isinstance(c, dict) and c.get("cid") is not None:
            ids[c["id"]] = c["cid"]
    resolve = chain_resolver(cfg, dict(state or {}, chainIds=ids))
    out = dict(fresh)
    for field, key in (("tokens", "chain"), ("protocols", "chain"), ("chains", "id")):
        kept = [dict(x, _chainoff_at=x.get("_chainoff_at") or old.get("fetchedAt"))
                for x in old.get(field) or [] if isinstance(x, dict) and resolve(x.get(key)) in off]
        out[field] = [x for x in fresh.get(field) or [] if not (isinstance(x, dict) and resolve(x.get(key)) in off)] + kept
    out["total"] = (_num(fresh.get("total"))
                    - sum(_num(x.get("usd")) for x in fresh.get("chains") or [] if isinstance(x, dict) and resolve(x.get("id")) in off)
                    + sum(_num(x.get("usd")) for x in old.get("chains") or [] if isinstance(x, dict) and resolve(x.get("id")) in off))
    return out


def refresh_once(cfg: dict, path: str, now: float = None, get=None, sleep=time.sleep, log=None, bot_usd: dict = None) -> str:
    s = settings(cfg)
    if not s["enabled"]:
        return "off"
    now = time.time() if now is None else float(now)
    st = load_state(path)
    st.setdefault("v", 1)
    st.setdefault("wallets", {})
    if float(st.get("backoffUntil") or 0) > now:
        return "cooldown"
    day = time.strftime("%Y-%m-%d", time.gmtime(now + 9 * 3600))
    calls = st.get("calls") if isinstance(st.get("calls"), dict) else {}
    if int(calls.get(day) or 0) + 2 > int(s["daily_calls_max"]):
        return "cap"
    if bot_usd is None and s["min_wallet_usd"] > 0:
        return "idle"
    addrs = watch_addrs(st, evm_wallets(cfg), bot_usd, s["min_wallet_usd"])
    a = due_wallet(st, addrs, now, s["wallet_every_h"] * 3600, bot_usd)
    if not a:
        return "idle"
    n = {"c": 0}

    def counted(u):
        n["c"] += 1
        return (get or (lambda x: http_get(x, s["timeout_sec"])))(u)
    res, err = "ok", None
    try:
        prev9 = dict(st["wallets"].get(a) or {})
        d = fetch_wallet(a, get=counted, sleep=sleep, gap=s["gap_sec"], timeout=s["timeout_sec"],
                         want_protocols=lambda tot9: need_protocols(prev9, (bot_usd or {}).get(a) if isinstance(bot_usd, dict) else None, tot9, now=now))
    except RateLimited as e:
        res, err = "ratelimited", common.safe_err(e)
    except Exception as e:
        res, err = "error", f"{type(e).__name__}: {common.safe_err(e)[:160]}"
    st = load_state(path) or st
    st.setdefault("v", 1)
    st.setdefault("wallets", {})
    calls = st.get("calls") if isinstance(st.get("calls"), dict) else {}
    calls = {k: v for k, v in calls.items() if k >= time.strftime("%Y-%m-%d", time.gmtime(now + 9 * 3600 - 7 * 86400))}
    calls[day] = int(calls.get(day) or 0) + n["c"]
    st["calls"] = calls
    w = dict(st["wallets"].get(a) or {})
    w["triedAt"] = int(now)
    if res == "ok":
        w.update(_freeze_disabled(cfg, st, w, d))
        w["fetchedAt"] = int(time.time() if now is None else now)
        w.pop("err", None)
        ids = dict(st.get("chainIds") or {})
        nms = dict(st.get("chainNames") or {})
        for c in d.get("chains") or []:
            if c.get("cid") is not None:
                ids[c["id"]] = c["cid"]
            nms[c["id"]] = c.get("name") or c["id"]
        st["chainIds"], st["chainNames"] = ids, nms
        st["backoffSec"] = 0
        st.pop("lastErr", None)
    else:
        w["err"] = err
        st["lastErr"] = {"t": int(now), "err": err, "addr": a}
        if res == "ratelimited":
            b = float(st.get("backoffSec") or 0)
            b = s["backoff_sec"] if b <= 0 else min(b * 2, s["backoff_max_sec"])
            st["backoffSec"] = b
            st["backoffUntil"] = int(now + b)
    st["wallets"][a] = w
    st["updated"] = int(now)
    _write(path, st)
    if log:
        log("rabby-worker: %s %s%s (호출 %d)" % (a[:8], res, f" — {err}" if err else "", n["c"]))
    return res


def token_ok(t: dict, spam_fn=None, bc=None, min_usd: float = 0.01):
    if t.get("scam") or t.get("sus"):
        return False, "Rabby 스캠·의심"
    if not (t.get("v") or t.get("c")):
        return False, "Rabby 미검증"
    usd = _num(t.get("amt")) * _num(t.get("px"))
    if not (_num(t.get("px")) > 0 and _num(t.get("amt")) > 0):
        return False, "가격·수량 없음"
    if usd < min_usd:
        return False, "먼지"
    if spam_fn:
        why = spam_fn(t.get("sym"), bc, t.get("id"))
        if why:
            return False, why
    return True, None


def _ca(t: dict, rid: str) -> str:
    i = str(t.get("id") or "").lower()
    return i if i.startswith("0x") and len(i) == 42 else ZERO


def merge(state: dict, *, resolve, wallet_chains_set: set, known_pairs: set, held_chains: set = frozenset(),
          lp_ids: set = frozenset(), priced_held: dict = None, spam_fn=None, labels: dict = None,
          chain_names: dict = None, now: float = None, min_usd: float = 0.01, only_addrs=None, skip_proto=None) -> dict:
    now = time.time() if now is None else now
    labels = labels or {}
    priced_held = priced_held or {}
    items, debts, wallets = [], [], {}
    for addr, w in sorted(((state or {}).get("wallets") or {}).items()):
        if only_addrs is not None and addr not in only_addrs:
            continue
        if not isinstance(w, dict) or not w.get("fetchedAt"):
            continue
        fat = int(w["fetchedAt"])
        wv = {"rabby": round(_num(w.get("total")), 2), "only": 0.0, "onlyDebt": 0.0, "fetchedAt": fat, "skipped": {}, "top": [],
              "err": w.get("err")}
        wallets[addr] = wv

        def tracked_chain(bc):
            return bool(bc) and ((addr, bc) in wallet_chains_set or (bc, addr) in held_chains)

        def skip(why, usd):
            wv["skipped"][why] = round(wv["skipped"].get(why, 0.0) + usd, 2)

        for t in w.get("tokens") or []:
            rid = t.get("chain") or ""
            bc = resolve(rid)
            usd = _num(t.get("amt")) * _num(t.get("px"))
            if tracked_chain(bc) and (_ca(t, rid) == ZERO or (bc, _ca(t, rid)) in known_pairs):
                continue
            ok, why = token_ok(t, spam_fn, bc, min_usd)
            if not ok:
                skip(why, usd)
                continue
            kind = "missed" if tracked_chain(bc) else "chain"
            items.append({"addr": addr, "rid": rid, "bc": bc, "sym": t.get("sym") or "?", "amt": _num(t["amt"]), "px": _num(t["px"]),
                          "usd": usd, "proto": "", "pname": "", "kind": kind, "at": int(t.get("_chainoff_at") or fat),
                          "chain": chain_label(state, rid, chain_names),
                          "ca": _ca(t, rid)})
        for p in w.get("protocols") or []:
            rid = p.get("chain") or ""
            bc = resolve(rid)
            why9 = skip_proto(addr, str(p.get("proto") or ""), str(p.get("pname") or "")) if skip_proto else None
            if why9:
                skip(why9, sum(_num(x.get("amt")) * _num(x.get("px")) for it in p.get("items") or [] for x in it.get("assets") or []))
                continue
            for it in p.get("items") or []:
                skip_assets = False
                a_usd = sum(_num(x.get("amt")) * _num(x.get("px")) for x in it.get("assets") or [])
                if bc and it.get("idx") and (bc, str(it["idx"])) in lp_ids:
                    skip_assets = True
                if not skip_assets and tracked_chain(bc):
                    if any((bc, x) in known_pairs for x in (it.get("pool"), it.get("ctrl")) if x):
                        skip_assets = True
                    if not skip_assets and a_usd > 0:
                        sups = {str(x.get("sym") or "").upper() for x in it.get("assets") or [] if len(str(x.get("sym") or "")) >= 3}
                        hv = sum(u for s9, u in priced_held.get((bc, addr), ())
                                 if any(s0 in s9 and s0 != s9 for s0 in sups))
                        if hv > 0 and 0.5 * a_usd <= hv <= 2 * a_usd:
                            skip("봇 영수 토큰으로 추정", a_usd)
                            skip_assets = True
                good = []
                for x in ([] if skip_assets else (it.get("assets") or [])):
                    ok, why = token_ok(x, spam_fn, bc, min_usd)
                    if ok:
                        good.append(x)
                    else:
                        skip(why, _num(x.get("amt")) * _num(x.get("px")))
                if not good and not it.get("debts"):
                    continue
                pn = str(p.get("pname") or p.get("proto") or "")
                nm = str(it.get("name") or "")
                for x in good:
                    items.append({"addr": addr, "rid": rid, "bc": bc, "sym": x.get("sym") or "?", "amt": _num(x["amt"]), "px": _num(x["px"]),
                                  "usd": _num(x["amt"]) * _num(x["px"]), "proto": p.get("proto") or "", "pname": pn, "iname": nm,
                                  "idx": it.get("idx") or "", "kind": "proto", "at": int(p.get("_chainoff_at") or fat), "chain": chain_label(state, rid, chain_names)})
                for x in it.get("debts") or []:
                    u = _num(x.get("amt")) * _num(x.get("px"))
                    if u <= 0:
                        continue
                    debts.append({"addr": addr, "rid": rid, "bc": bc, "sym": x.get("sym") or "?", "qty": -_num(x["amt"]), "px": _num(x["px"]),
                                  "usd": -u, "proto": p.get("proto") or "", "pname": pn, "iname": nm, "at": int(p.get("_chainoff_at") or fat),
                                  "chain": chain_label(state, rid, chain_names)})
    for x in items:
        wallets[x["addr"]]["only"] += x["usd"]
    for x in debts:
        wallets[x["addr"]]["onlyDebt"] += x["usd"]
    for a, wv in wallets.items():
        mine = sorted((x for x in items if x["addr"] == a), key=lambda x: -x["usd"])
        wv["top"] = [{"sym": x["sym"], "chain": x["chain"], "usd": round(x["usd"], 2),
                      "where": (x["pname"] + (" " + x.get("iname") if x.get("iname") else "")) if x["kind"] == "proto" else
                      ("봇이 놓친 토큰" if x["kind"] == "missed" else "추적 안 하는 체인")} for x in mine[:5]]
        wv["only"] = round(wv["only"], 2)
        wv["onlyDebt"] = round(wv["onlyDebt"], 2)
    return {"items": items, "debts": debts, "wallets": wallets,
            "onlyUsd": round(sum(x["usd"] for x in items), 2), "debtUsd": round(sum(x["usd"] for x in debts), 2),
            "at": min((x["at"] for x in items + debts), default=None)}


def short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if a and len(a) > 12 else str(a or "")


_KIND_KO = (("lock", "스테이킹"), ("stak", "스테이킹"), ("vest", "스테이킹"), ("liquidity", "LP"), ("lend", "예치"),
            ("suppl", "예치"), ("deposit", "예치"), ("yield", "예치"), ("farm", "예치"), ("reward", "보상"))


def kind_ko(x: dict) -> str:
    if x.get("kind") == "proto":
        nm = str(x.get("iname") or "").lower()
        return next((ko for k, ko in _KIND_KO if k in nm), "예치")
    return "미추적 토큰" if x.get("kind") == "missed" else ""


def rows_for(m: dict, labels: dict, now: float) -> list:
    by = {}
    for x in m.get("items") or []:
        k = str(x["sym"]).upper()
        r = by.setdefault(k, {"sym": x["sym"], "qty": 0.0, "usd": 0.0, "at": x["at"], "chains": [], "locs": [], "n": 0, "kinds": []})
        kk = kind_ko(x)
        if kk not in r["kinds"]:
            r["kinds"].append(kk)
        r["qty"] += x["amt"]
        r["usd"] += x["usd"]
        r["at"] = min(r["at"], x["at"])
        r["n"] += 1
        if x["chain"] not in r["chains"]:
            r["chains"].append(x["chain"])
        lab = labels.get(x["addr"]) or x["addr"][:8]
        w = lab if str(lab).rstrip().endswith("지갑") else f"{lab} 지갑"
        if x["kind"] == "proto":
            sub = f"{x['chain']} · {x['pname']}" + (f" {x.get('iname')}" if x.get("iname") else "") \
                  + (f" #{x['idx']}" if str(x.get("idx") or "").isdigit() else "") + f" · {short(x['addr'])} · Rabby 기준"
        else:
            sub = f"{x['chain']} · {short(x['addr'])} · Rabby 기준" + (" (봇 미추적 토큰)" if x["kind"] == "missed" else "")
        r["locs"].append({"w": w, "ch": x["chain"], "sub": sub, "qty": x["amt"], "rb": 1,
                          "loc": f"rabby:{x['rid']}:{x['addr']}" + (f":{x['proto']}" if x["proto"] else ""),
                          "usd": round(x["usd"], 2), "pname": x.get("pname") or "", "iname": x.get("iname") or "", "rbKind": kk})
    out = []
    for k, r in sorted(by.items(), key=lambda kv: -kv[1]["usd"]):
        if r["qty"] <= 0:
            continue
        px = r["usd"] / r["qty"]
        out.append({"key": f"rb:{k}", "sym": r["sym"], "name": f"{r['sym']} · " + "/".join(r["chains"]),
                    "qty": r["qty"], "price": px, "avg": 0, "kqty": 0, "fbQty": 0, "fbCost": 0,
                    "pxSrc": "rabby", "pxAge": int(max(0, now - r["at"])), "symSrc": "rabby",
                    "rabby": {"at": int(r["at"]), "n": r["n"]}, "locs": r["locs"],
                    "rbKind": r["kinds"][0] if len(r["kinds"]) == 1 else ""})
    return out


def debt_rows(m: dict, labels: dict) -> list:
    out = []
    for x in m.get("debts") or []:
        lab = labels.get(x["addr"]) or x["addr"][:8]
        out.append({"sym": x["sym"], "qty": x["qty"], "price": x["px"], "usd": round(x["usd"], 2), "chain": x["chain"],
                    "where": f"{x['pname']}" + (f" {x.get('iname')}" if x.get("iname") else ""), "wallet": lab,
                    "addr": x["addr"], "at": int(x["at"]), "loc": f"rabby:{x['rid']}:{x['addr']}:{x['proto']}"})
    return out


def daily_note(path: str, date_iso: str, usd: float, now: float, per_wallet: dict = None) -> dict:
    d = load_state(path)
    if not isinstance(d.get("d"), dict):
        d = {"first": None, "d": {}}
    if usd == 0 and not d.get("first"):
        return d
    before = json.dumps({k: d.get(k) for k in ("first", "d", "wf", "n")}, sort_keys=True)
    if not d.get("first"):
        d["first"] = date_iso
    d["d"][date_iso] = round(float(usd), 2)
    wf = d.get("wf") if isinstance(d.get("wf"), dict) else {}
    for a, v in (per_wallet or {}).items():
        if a not in wf and abs(float(v or 0)) >= 0.01:
            wf[a] = date_iso
    d["wf"] = wf
    n = d.get("n") if isinstance(d.get("n"), dict) else {}
    if per_wallet is not None:
        nv = round(sum(float(v or 0) for a, v in per_wallet.items() if wf.get(a) == date_iso), 2)
        if nv:
            n[date_iso] = nv
        else:
            n.pop(date_iso, None)
    elif date_iso == d["first"]:
        n[date_iso] = round(float(usd), 2)
    keep = sorted(d["d"])[-120:]
    d["d"] = {k: d["d"][k] for k in keep}
    d["n"] = {k: v for k, v in n.items() if k >= keep[0]}
    if json.dumps({k: d.get(k) for k in ("first", "d", "wf", "n")}, sort_keys=True) != before and now - float(d.get("_w") or 0) >= 60:
        d["_w"] = int(now)
        try:
            _write(path, d)
        except OSError:
            pass
    return d


def day_values(note: dict, isos, today_iso: str, today_usd: float) -> dict:
    first = (note or {}).get("first")
    out = {}
    if not first:
        return out
    rec = dict((note or {}).get("d") or {})
    rec[today_iso] = today_usd
    ks = sorted(rec)
    for iso in sorted(set(isos or ())):
        if iso < first:
            continue
        v = rec.get(iso)
        if v is None:
            prev = [k for k in ks if k <= iso]
            if not prev:
                continue
            v = rec[prev[-1]]
        v = round(float(v), 2)
        if v:
            out[iso] = v
    return out


def daily_overlay(daily: list, note: dict, today_iso: str, today_usd: float, year: int = None) -> None:
    first = (note or {}).get("first")
    if not first or not daily:
        return
    rec = dict((note or {}).get("d") or {})
    rec[today_iso] = today_usd
    newv = dict((note or {}).get("n") or {})
    if first not in newv and not (note or {}).get("wf"):
        newv[first] = rec.get(first, 0)
    ks = sorted(rec)
    y = int(today_iso[:4])
    tmd = today_iso[5:10]
    for row in daily:
        md = str(row.get("date") or "")
        if len(md) != 5:
            continue
        iso = f"{y if md <= tmd else y - 1}-{md}"
        if iso < first:
            continue
        v = rec.get(iso)
        if v is None:
            prev = [k for k in ks if k <= iso]
            if not prev:
                continue
            v = rec[prev[-1]]
        v = round(float(v), 2)
        if not v:
            continue
        row["val"] = round(float(row.get("val") or 0) + v, 2)
        row["rb"] = v
        nv = round(float(newv.get(iso) or 0), 2)
        if nv:
            row["rbNew"] = nv


GAP_NAME = "rabby_gap.json"


def gap_over(bot: float, rb: float, min_usd: float = 200.0, pct: float = 0.05) -> bool:
    return (rb - bot) > max(min_usd, pct * max(bot, 0.0))


def gap_track(path: str, recon: list, now: float, min_usd: float = 200.0, pct: float = 0.05,
              stale_sec: float = 3 * 86400) -> dict:
    old = load_state(path).get("since") or {}
    cur = {}
    for r in recon or []:
        if now - float(r.get("fetchedAt") or 0) > stale_sec:
            continue
        bot9 = float(r.get("bot") or 0)
        rb9 = bot9 + float(r["rest"]) if isinstance(r.get("rest"), (int, float)) else float(r.get("rabby") or 0)
        if gap_over(bot9, rb9, min_usd, pct):
            cur[r["addr"]] = int(old.get(r["addr"]) or now)
    if cur != old:
        try:
            _write(path, {"since": cur, "t": int(now)})
        except OSError:
            pass
    return cur


def hl_proto(proto: str, pname: str) -> bool:
    p9, n9 = str(proto or "").lower(), str(pname or "").strip().lower()
    return p9 == "hyperliquid" or p9.endswith("_hyperliquid") or n9 == "hyperliquid"
