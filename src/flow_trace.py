"""Traces funds sent to unknown addresses."""
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

import bf_engine
import netpace
import common
import xchain_match as xm
import spamguard

CACHE_NAME = "flow_trace_cache.json"
CACHE_V = 1
ELIGIBLE = ("pending", "bridge_untracked", "returned", "external")
MIN_USD = 100.0
PER_DEST_CALLS = int(os.environ.get("FLOW_PER_DEST_CALLS", "600"))
REFRESH_SEC = 7 * 86400
RETRY_SEC = 3600
SCAN_TIMEOUT_SEC = 6 * 3600
SCAN_IDLE_SEC = 2 * 3600
SOL_SIG_PAGE = 1000
SOL_SIG_PAGES = 4
SOL_TX_MAX = 500
EVM_PAGES = 12
BSC_WINDOWS = 8
BSC_SENDS = 8
ES_API = "https://api.etherscan.io/v2/api"
ES_PAGE = 200
RPCWIN_WINDOWS = 4
RPCWIN_COVER_SEC = 2 * 3600
RPCWIN_MAX_WINDOWS = 12
RPCWIN_SENDS = 4
BS403_SEC = 86400
ES_UNSUP_SEC = 7 * 86400
ES_UNSUP_RE = re.compile(r"not supported|unsupported chain|upgrade your api plan|not available (?:on|for) (?:the )?free|free api access|chain.*not.*(?:supported|available)", re.I)
BS_BLOCKED = common.BS_BLOCKED
SOL_SPEND_MIN = Decimal("0.02")
DUST_USD = 1.0
HID_KEEP = 30
TOKEN_PROGS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
WSOL = xm.WSOL
TR = xm.TR
STABLE_SYMS = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "BUSD", "USD1", "PYUSD", "USDG", "TUSD"}
NATIVE = xm.NATIVE
CHAIN_KO = xm.CHAIN_KO


class EsUnsupported(RuntimeError):
    pass


def D(x) -> Decimal:
    return xm.D(x)


def norm(a) -> str:
    return xm.norm(a)


def short(a) -> str:
    return xm.short(a)


_BURN = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead",
         "11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111"}


def is_burn(a) -> bool:
    a = norm(a)
    if a in _BURN:
        return True
    if isinstance(a, str) and a.startswith("0x") and len(a) == 42:
        try:
            return int(a, 16) <= 0xFFFF
        except ValueError:
            return False
    return False


def _stable_map():
    try:
        import pricing
        return ({c: {norm(k): v for k, v in m.items()} for c, m in pricing.STABLE_CAS.items()}, dict(pricing.STABLE_MINTS))
    except Exception:
        return ({}, {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"})


STABLE_CAS, STABLE_MINTS = _stable_map()


def stable_sym(chain, token):
    if chain == "sol":
        return STABLE_MINTS.get(token)
    return (STABLE_CAS.get(chain) or {}).get(norm(token))


def load_cache(state_dir):
    p = os.path.join(state_dir, CACHE_NAME)
    try:
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    if not isinstance(c, dict) or c.get("v") != CACHE_V:
        c = {"v": CACHE_V}
    c.setdefault("dest", {})
    return c


def save_cache(state_dir, cache):
    p = os.path.join(state_dir, CACHE_NAME)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, p)


def fingerprint(row) -> str:
    return f"{int(row.get('count') or 0)}|{int(row.get('lastTs') or 0)}"


def candidates(rows, cache, now=None, min_usd=MIN_USD):
    now = now or time.time()
    out = []
    for r in rows or []:
        a = r.get("address") or ""
        if r.get("status") not in ELIGIBLE or a in ("multi", "?") or r.get("dust") or is_burn(a):
            continue
        val = max(float(r.get("usdAtSend") or 0), float(r.get("usdNow") or 0))
        if val < min_usd:
            continue
        e = (cache.get("dest") or {}).get(a) or {}
        fp = fingerprint(r)
        st = e.get("status")
        if e.get("fp") == fp:
            if st == "ok" and now - float(e.get("t") or 0) < REFRESH_SEC:
                continue
            if st == "partial" and now - float(e.get("t") or 0) < REFRESH_SEC:
                continue
            if st in ("error", "budget", "paused") and now - float(e.get("rt") or 0) < (RETRY_SEC if st == "error" else 60):
                continue
        sends = [{"chain": t.get("chain"), "tx": t.get("tx"), "ts": int(t.get("ts") or 0), "sym": t.get("sym"),
                  "qty": t.get("qty"), "usd": t.get("usdAtSend")} for t in (r.get("txs") or [])]
        out.append({"dest": a, "chains": list(r.get("chains") or []), "first": int(r.get("firstTs") or 0),
                    "last": int(r.get("lastTs") or 0), "fp": fp, "sends": sends, "val": val,
                    "_ord": (0 if st in ("budget", "paused", "running") else 1, -val)})
    out.sort(key=lambda c: c["_ord"])
    for c in out:
        c.pop("_ord", None)
    return out


def sol_events(A, sig, ct, sym_of=None):
    if not ct or ct.get("err"):
        return []
    sym_of = sym_of or (lambda m: None)
    tok, sol = xm.sol_owner_deltas(ct, A)
    if WSOL in tok:
        sol += tok.pop(WSOL)
    neg, pos = {}, {}
    for m, q in tok.items():
        if q < 0:
            neg[m] = -q
        elif q > 0:
            pos[m] = q
    if sol <= -SOL_SPEND_MIN:
        neg["SOL"] = -sol - Decimal(ct.get("fee") or 0) / Decimal(10 ** 9) if -sol > Decimal(ct.get("fee") or 0) / Decimal(10 ** 9) else -sol
    elif sol >= Decimal("0.001"):
        pos["SOL"] = sol
    ts = int(ct.get("ts") or 0)

    def sy(m):
        return "SOL" if m == "SOL" else (STABLE_MINTS.get(m) or sym_of(m) or short(m))

    def lg(m, q):
        return {"chain": "sol", "token": "native" if m == "SOL" else m, "sym": sy(m), "qty": str(q)}
    if neg and pos:
        return [{"kind": "swap", "ts": ts, "tx": sig, "chain": "sol",
                 "sold": [lg(m, q) for m, q in neg.items()], "bought": [lg(m, q) for m, q in pos.items()]}]
    ev = []
    pre = {b["i"]: b for b in ct.get("ptb") or []}
    post = {b["i"]: b for b in ct.get("qtb") or []}

    def cp_token(m, sign):
        best, amt = None, 0
        for i in set(pre) | set(post):
            b = post.get(i) or pre.get(i)
            if b.get("mint") != m or b.get("owner") in (None, A):
                continue
            d = int((post.get(i) or {}).get("amt") or 0) - int((pre.get(i) or {}).get("amt") or 0)
            if (sign > 0 and d > amt) or (sign < 0 and d < amt):
                best, amt = b.get("owner"), d
        return best

    def cp_sol(sign):
        keys, a0, a1 = ct.get("keys") or [], ct.get("pre") or [], ct.get("post") or []
        best, amt = None, 0
        for i, k in enumerate(keys):
            if k == A or i >= len(a0) or i >= len(a1):
                continue
            d = a1[i] - a0[i]
            if (sign > 0 and d > amt) or (sign < 0 and d < amt):
                best, amt = k, d
        return best
    for m, q in neg.items():
        cp = cp_sol(+1) if m == "SOL" else cp_token(m, +1)
        ev.append(dict(lg(m, q), kind="out", ts=ts, tx=sig, cp=cp or "?"))
    for m, q in pos.items():
        cp = cp_sol(-1) if m == "SOL" else cp_token(m, -1)
        ev.append(dict(lg(m, q), kind="in", ts=ts, tx=sig, cp=cp or "?"))
    return ev


def evm_events(H, chain, legs):
    H = norm(H)
    by = {}
    for lg in legs:
        by.setdefault(lg["tx"], []).append(lg)
    ev = []
    for tx, ls in by.items():
        outs = [x for x in ls if x["dir"] == "out"]
        ins = [x for x in ls if x["dir"] == "in"]
        ts = max(int(x.get("ts") or 0) for x in ls)

        def pk(x):
            return {"chain": chain, "token": x["token"], "sym": x.get("sym") or "?", "qty": x["qty"],
                    **({"rate": x["rate"]} if x.get("rate") else {})}
        if outs and ins and {x["token"] for x in outs} != {x["token"] for x in ins}:
            net = {}
            for x in outs:
                net.setdefault(x["token"], [x, Decimal(0)])[1] -= D(x["qty"])
            for x in ins:
                net.setdefault(x["token"], [x, Decimal(0)])[1] += D(x["qty"])
            sold = [dict(pk(x), qty=str(-q)) for x, q in net.values() if q < 0]
            bought = [dict(pk(x), qty=str(q)) for x, q in net.values() if q > 0]
            if sold and bought:
                ev.append({"kind": "swap", "ts": ts, "tx": tx, "chain": chain, "sold": sold, "bought": bought})
                continue
        for x in outs + ins:
            e = dict(pk(x), kind=x["dir"], ts=int(x.get("ts") or 0), tx=tx, cp=norm(x.get("cp")) or "?")
            if x.get("cp_contract"):
                e["cpc"] = 1
            if x.get("cp_name"):
                e["cpn"] = str(x["cp_name"])[:40]
            ev.append(e)
    return ev


def _bs_ts(s):
    try:
        import calendar
        return calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def bs_token_legs(H, items, direction):
    H = norm(H)
    out = []
    for it in items or []:
        tk = it.get("token") or {}
        try:
            dec = int((it.get("total") or {}).get("decimals") or tk.get("decimals") or 18)
            q = D((it.get("total") or {}).get("value")) / (Decimal(10) ** dec)
        except (ValueError, TypeError, InvalidOperation):
            continue
        if q <= 0:
            continue
        cpo = it.get("to" if direction == "out" else "from") or {}
        if tk.get("reputation") == "scam" or (cpo.get("is_scam") and direction == "in"):
            continue
        nm = cpo.get("name") or ", ".join(t.get("name") for t in ((cpo.get("metadata") or {}).get("tags") or [])[:2] if t.get("name")) or None
        out.append({"tx": norm(it.get("transaction_hash") or it.get("tx_hash")), "ts": _bs_ts(it.get("timestamp")),
                    "block": int(it.get("block_number") or 0), "dir": direction, "cp": norm(cpo.get("hash")),
                    "cp_contract": bool(cpo.get("is_contract")), "cp_name": nm, "token": norm(tk.get("address_hash") or tk.get("address")),
                    "sym": tk.get("symbol") or "?", "qty": str(q), "rate": tk.get("exchange_rate")})
    return out


def bs_native_legs(H, items, chain):
    out = []
    for it in items or []:
        try:
            v = D(it.get("value")) / Decimal(10 ** 18)
        except (ValueError, TypeError, InvalidOperation):
            continue
        if v <= 0 or str(it.get("status") or "ok") not in ("ok", "success"):
            continue
        to = it.get("to") or {}
        nm = to.get("name") or None
        out.append({"tx": norm(it.get("hash")), "ts": _bs_ts(it.get("timestamp")), "block": int(it.get("block_number") or it.get("block") or 0),
                    "dir": "out", "cp": norm(to.get("hash")), "cp_contract": bool(to.get("is_contract")), "cp_name": nm,
                    "token": "native", "sym": NATIVE.get(chain, "ETH"), "qty": str(v)})
    return out


def es_token_legs(H, rows):
    H = norm(H)
    out = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        f, t = norm(it.get("from")), norm(it.get("to"))
        if H not in (f, t) or f == t:
            continue
        try:
            dec = int(it.get("tokenDecimal") or 18)
            q = D(it.get("value")) / (Decimal(10) ** dec)
        except (ValueError, TypeError, InvalidOperation):
            continue
        if q <= 0:
            continue
        d9 = "out" if f == H else "in"
        try:
            ts9, bn9 = int(it.get("timeStamp") or 0), int(it.get("blockNumber") or 0)
        except (TypeError, ValueError):
            continue
        lg9 = {"tx": norm(it.get("hash")), "ts": ts9, "block": bn9, "dir": d9, "cp": t if d9 == "out" else f,
               "cp_contract": False, "cp_name": None, "token": norm(it.get("contractAddress")),
               "sym": str(it.get("tokenSymbol") or "?")[:24], "qty": str(q)}
        if str(it.get("logIndex") or "").strip().isdigit():
            lg9["li"] = int(str(it.get("logIndex")).strip())
        out.append(lg9)
    return out


def leg_key(x) -> tuple:
    if x.get("li") is not None:
        return (x.get("tx"), "li", x.get("li"))
    return (x.get("tx"), x.get("dir"), x.get("cp"), x.get("token"), str(x.get("qty")))


def es_native_legs(H, rows, chain):
    H = norm(H)
    out = []
    for it in rows or []:
        if not isinstance(it, dict) or norm(it.get("from")) != H or str(it.get("isError") or "0") != "0":
            continue
        try:
            v = D(it.get("value")) / Decimal(10 ** 18)
            ts9, bn9 = int(it.get("timeStamp") or 0), int(it.get("blockNumber") or 0)
        except (ValueError, TypeError, InvalidOperation):
            continue
        if v <= 0:
            continue
        out.append({"tx": norm(it.get("hash")), "ts": ts9, "block": bn9, "dir": "out", "cp": norm(it.get("to")),
                    "cp_contract": False, "cp_name": None, "token": "native", "sym": NATIVE.get(chain, "ETH"), "qty": str(v)})
    return out


def log_legs(H, logs, dec_of, sym_of, ts_of):
    H = norm(H)
    out = []
    for lg in logs or []:
        tp = lg.get("topics") or []
        if len(tp) != 3 or tp[0] != TR:
            continue
        f, t = norm("0x" + tp[1][26:]), norm("0x" + tp[2][26:])
        if H not in (f, t):
            continue
        try:
            v = int(lg.get("data") or "0x0", 16)
        except ValueError:
            continue
        tok = norm(lg.get("address"))
        q = Decimal(v) / (Decimal(10) ** dec_of(tok))
        if q <= 0:
            continue
        bn = int(lg.get("blockNumber") or "0x0", 16)
        out.append({"tx": norm(lg.get("transactionHash")), "ts": ts_of(bn), "block": bn, "dir": "out" if f == H else "in",
                    "cp": t if f == H else f, "cp_contract": False, "cp_name": None, "token": tok, "sym": sym_of(tok), "qty": str(q)})
    return out


class Scanner:

    def __init__(self, cfg, cache, px=None, budget=40, sleep=0.35, log=None, sym_of=None):
        try:
            import evm_watch
            chains9 = {}
            for ch9, cc9 in (cfg.get("chains") or {}).items():
                if not isinstance(cc9, dict) or ch9 in ("sol", "bsc"):
                    chains9[ch9] = cc9
                    continue
                cc9 = dict(cc9)
                if not cc9.get("rpcs") or not cc9.get("rpc_logs"):
                    nd9 = evm_watch.rpc_nodes(cfg, ch9)
                    if not cc9.get("rpcs"):
                        cc9["rpcs"] = list(nd9.get("detail") or [])
                    if not cc9.get("rpc_logs"):
                        cc9["rpc_logs"] = list(nd9.get("logs") or cc9.get("rpcs") or [])
                chains9[ch9] = cc9
            cfg = dict(cfg, chains=chains9)
        except Exception:
            pass
        memo = cache.setdefault("_memo", {})
        for k in ("etx", "blk", "dec"):
            memo.setdefault(k, {})
        if len(memo["blk"]) > 5000:
            memo["blk"].clear()
        self.t = xm.Tracer(cfg, {"stx": {}, "sigs": {}, "ws": {}, "etx": memo["etx"], "blk": memo["blk"], "dec": memo["dec"],
                                 "inflows": {}, "outflows": {}}, None, xm.load_seed(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           px=px, budget=budget, sleep=sleep, log=log)
        self.cfg, self.c, self.px, self.log = cfg, cache, px, log or (lambda *a: None)
        self.sym_of = sym_of or (lambda chain, token: None)

    @property
    def calls(self):
        return self.t.calls

    CANDLE_RESERVE = 6

    def _px_at(self, sym, ts):
        if not self.px or not ts:
            return None, False
        sym = str(sym).upper()
        ms = (int(ts) // 60) * 60_000
        day = f"{sym}:{int(ts) // 86400}"
        memo = self.c.setdefault("_memo", {}).setdefault("pxday", {})
        try:
            with self.px.lock:
                hit = (self.px.d.get("candle") or {}).get(f"{sym}:{ms}")
            if hit:
                return float(hit), False
            if memo.get(day):
                return float(memo[day]), True
            na9 = getattr(self.px, "neg_active", None)
            if na9(sym) if na9 else (time.time() - float((self.px.d.get("neg_ts") or {}).get(sym, 0) or 0) < self.px.NEG_TTL):
                return None, False
            if self.t.calls + self.CANDLE_RESERVE > self.t.budget:
                return None, False
            try:
                netpace.wait("https://api.binance.com/api/v3/klines")
            except netpace.Cooldown:
                return None, False
            self.t.calls += self.CANDLE_RESERVE
            p = self.px.candle_usd(sym, ms)
            time.sleep(self.t.sleep)
        except Exception:
            return None, False
        if p:
            if len(memo) > 3000:
                memo.clear()
            memo[day] = float(p)
            return float(p), False
        return None, False

    def value(self, leg, ts):
        q = float(D(leg.get("qty")))
        ss = stable_sym(leg["chain"], leg["token"]) if leg.get("token") != "native" else None
        if ss:
            return round(q, 2), "stable"
        if leg.get("token") == "native":
            p, apx = self._px_at(NATIVE.get(leg["chain"], "SOL") if leg["chain"] != "sol" else "SOL", ts)
            if p:
                return round(q * p, 2), ("candle_day" if apx else "candle")
        return None, None

    def _price_events(self, evs):
        for e in evs:
            for lg in ([e] if e["kind"] in ("out", "in") else e.get("sold", []) + e.get("bought", [])):
                if lg.get("usd") is None:
                    u, src = self.value(lg, e["ts"])
                    if u is not None:
                        lg["usd"], lg["ps"] = u, src
                        if src == "candle_day":
                            lg["apx"] = 1

    BRIDGE_MARKS = ("relay", "spokepool", "dlnsource", "debridge", "wormhole", "ccip", "stargate", "portal", "tokenbridge",
                    "l1standardbridge", "bridge")

    def bridge_proto(self, e):
        c = (self.t.seed.get("evm_contracts") or {}).get(norm(e.get("cp")))
        if c:
            return c.get("proto") or "?"
        nm = str(e.get("cpn") or "").lower().replace(" ", "")
        if nm and any(m in nm for m in self.BRIDGE_MARKS):
            return "relay" if "relay" in nm else ("debridge" if ("dln" in nm or "debridge" in nm) else "?")
        return None

    def resolve_bridges(self, ent, evs, cap=10):
        br = ent.setdefault("br", {})
        n = 0
        for e in evs:
            if e.get("kind") != "out":
                continue
            proto = self.bridge_proto(e)
            if not proto:
                continue
            e["bp"] = proto
            k = norm(e["tx"])
            if k not in br:
                if n >= cap:
                    continue
                n += 1
                try:
                    ops = self.t.resolve(e["chain"], e["tx"], None if proto == "?" else proto)
                except xm.ApiDown:
                    continue
                op = next((o for o in ops if o and o.get("to")), None)
                br[k] = {"proto": (op or {}).get("proto") or proto, "dst": (op or {}).get("dst_chain"), "to": (op or {}).get("to"),
                         "dtx": (op or {}).get("dst_tx")} if op else {"proto": proto}
            if br.get(k, {}).get("to"):
                e["br"] = br[k]

    def scan_sol(self, ent, cand):
        A = cand["dest"]
        s = ent.setdefault("sol", {"sigs": [], "done": False, "cur": None, "newest": None, "ev": {}, "ntx": 0})
        since = cand["first"] - 60
        if s.get("done") and s.get("newest"):
            new, before = [], None
            for _ in range(SOL_SIG_PAGES):
                p = {"limit": SOL_SIG_PAGE, "until": s["newest"]}
                if before:
                    p["before"] = before
                r = self.t._sol("getSignaturesForAddress", [A, p]) or []
                new += [{"sig": x["signature"], "err": x.get("err") is not None, "ts": x.get("blockTime")} for x in r]
                if len(r) < SOL_SIG_PAGE:
                    break
                before = r[-1]["signature"]
            if new:
                s["sigs"] = new + s["sigs"]
                s["newest"] = new[0]["sig"]
        while not s.get("done"):
            p = {"limit": SOL_SIG_PAGE}
            if s.get("cur"):
                p["before"] = s["cur"]
            r = self.t._sol("getSignaturesForAddress", [A, p]) or []
            rows = [{"sig": x["signature"], "err": x.get("err") is not None, "ts": x.get("blockTime")} for x in r]
            if rows and not s.get("newest"):
                s["newest"] = rows[0]["sig"]
            s["sigs"] += rows
            s["pages"] = int(s.get("pages") or 0) + 1
            if len(r) < SOL_SIG_PAGE or (rows and int(rows[-1]["ts"] or 0) < since):
                s["done"] = True
            elif s["pages"] >= SOL_SIG_PAGES:
                s["done"], s["capped"] = True, "sigs"
            else:
                s["cur"] = rows[-1]["sig"]
        todo = [x for x in s["sigs"] if not x["err"] and int(x.get("ts") or 0) >= since and x["sig"] not in s["ev"]]
        todo.sort(key=lambda x: int(x.get("ts") or 0))
        for x in todo:
            if s["ntx"] >= SOL_TX_MAX:
                s["capped"] = "tx"
                break
            t = self.t._sol("getTransaction", [x["sig"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            s["ntx"] += 1
            ct = xm.compact_sol_tx(t)
            evs = sol_events(A, x["sig"], ct, lambda m: self.sym_of("sol", m))
            self._price_events(evs)
            s["ev"][x["sig"]] = evs
        bal = []
        b = self.t._sol("getBalance", [A]) or {}
        lam = int((b or {}).get("value") or 0)
        if lam:
            bal.append({"chain": "sol", "token": "native", "sym": "SOL", "qty": str(Decimal(lam) / Decimal(10 ** 9))})
        for prog in TOKEN_PROGS:
            r = self.t._sol("getTokenAccountsByOwner", [A, {"programId": prog}, {"encoding": "jsonParsed"}]) or {}
            for a in (r or {}).get("value") or []:
                try:
                    i = a["account"]["data"]["parsed"]["info"]
                    q = D(i["tokenAmount"]["uiAmountString"])
                except (KeyError, TypeError):
                    continue
                if q > 0:
                    bal.append({"chain": "sol", "token": i["mint"], "sym": STABLE_MINTS.get(i["mint"]) or self.sym_of("sol", i["mint"]) or short(i["mint"]),
                                "qty": str(q)})
        now = int(time.time())
        for lg in bal:
            u, src = self.value(lg, now)
            if u is not None:
                lg["usd"], lg["ps"] = u, src
        ent.setdefault("bal", {})["sol"] = {"t": now, "items": bal}

    def _bs(self, chain):
        if chain in BS_BLOCKED or common.chain_discovery(chain, (self.cfg.get("chains") or {}).get(chain)) == "rpc":
            return ""
        return self.t._bs(chain)

    def _bs_dead(self, chain) -> bool:
        t9 = ((self.c.get("_memo") or {}).get("bs403") or {}).get(chain)
        return bool(isinstance(t9, (int, float)) and time.time() - t9 < BS403_SEC and self._alt(chain))

    def _es_key(self) -> str:
        try:
            import settings_store
            return str(settings_store.env_value("TJ_ETHERSCAN_KEY") or "").strip()
        except Exception:
            return ""

    def _es_unsup(self, chain) -> bool:
        t9 = ((self.c.get("_memo") or {}).get("es_unsup") or {}).get(chain)
        return bool(isinstance(t9, (int, float)) and time.time() - t9 < ES_UNSUP_SEC)

    def _alt(self, chain):
        cc = (self.cfg.get("chains") or {}).get(chain) or {}
        if not isinstance(cc, dict) or chain in ("sol", "bsc"):
            return None
        if cc.get("etherscan_chainid") and self._es_key() and not self._es_unsup(chain):
            return "es"
        if cc.get("rpcs") or cc.get("rpc") or cc.get("rpc_logs"):
            return "rpcwin"
        return None

    def _scan_alt(self, ent, cand, chain):
        how = self._alt(chain)
        if how == "es":
            try:
                self.scan_evm_es(ent, cand, chain)
                return
            except EsUnsupported:
                self.c.setdefault("_memo", {}).setdefault("es_unsup", {})[chain] = int(time.time())
                (ent.get("evm") or {}).pop(chain, None)
                how = self._alt(chain)
        if how == "rpcwin":
            cc = (self.cfg.get("chains") or {}).get(chain) or {}
            try:
                spb = 86400.0 / float(cc.get("blocks_per_day")) if cc.get("blocks_per_day") else 2.0
            except (TypeError, ValueError, ZeroDivisionError):
                spb = 2.0
            span = self.t._span(chain)
            try:
                import evm_watch
                caps9 = evm_watch.rpc_nodes(self.cfg, chain).get("caps") or {}
                spans9 = [min(span, int(caps9.get(u) or span)) for u in self.t._evm_urls(chain, logs=True)]
                if spans9:
                    span = max(1, max(spans9))
            except Exception:
                pass
            wins = max(1, min(RPCWIN_MAX_WINDOWS, int(math.ceil(RPCWIN_COVER_SEC / max(1.0, span * spb)))))
            self.scan_rpcwin(ent, cand, chain, span, wins, RPCWIN_SENDS, spb)
        else:
            ent.setdefault("blocked", [])
            if chain not in ent["blocked"]:
                ent["blocked"].append(chain)

    def _es(self, chain, params):
        cid = ((self.cfg.get("chains") or {}).get(chain) or {}).get("etherscan_chainid")
        key = self._es_key()
        if not cid or not key:
            raise RuntimeError("이더스캔 키·체인 번호 없음")
        if not bf_engine.es_budget_take("web", kind="aux"):
            raise xm.Paused("이더스캔 하루 예산(보조 몫) — 다음 주기에 이어서")
        q = dict(params, chainid=cid, apikey=key)
        d = self._es_http(ES_API + "?" + urllib.parse.urlencode(q)) or {}
        res = d.get("result")
        if str(d.get("status")) == "1" and isinstance(res, list):
            return res
        msg = (str(d.get("message") or "") + " " + (res if isinstance(res, str) else "")).lower()
        if "no transactions found" in msg or "no records found" in msg:
            return []
        if "rate limit" in msg or "max calls" in msg or "limit reached" in msg:
            raise xm.Paused("이더스캔 한도 — 다음 주기에 이어서")
        if ES_UNSUP_RE.search(msg):
            raise EsUnsupported("이더스캔이 이 체인을 지원하지 않음(요금제)")
        raise RuntimeError("이더스캔 응답 오류: " + common.safe_err(msg)[:120])

    def _es_http(self, url, timeout=30):
        t = self.t
        if t.calls >= t.budget:
            raise xm.Budget()
        t.calls += 1
        req = urllib.request.Request(url, headers={"User-Agent": "tj-bot/0.1 (personal trade journal)", "Accept": "application/json"})
        try:
            netpace.wait(url)
        except netpace.Cooldown as e:
            raise xm.Paused(str(e))
        try:
            try:
                bf_engine.es_dispatch_wait(time.time() + 60)
            except bf_engine.NetError as e:
                raise xm.Paused("이더스캔 간격 대기 초과 — 다음 주기에 이어서") from e
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if netpace.note_error(url, e):
                raise xm.Paused(f"{netpace.host_of(url)} 429")
            raise RuntimeError(f"이더스캔 HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"이더스캔 연결 실패: {type(e.reason).__name__}") from None
        finally:
            time.sleep(t.sleep)

    def scan_evm_es(self, ent, cand, chain):
        H = norm(cand["dest"])
        st = ent.setdefault("evm", {}).setdefault(chain, {})
        since = cand["first"] - 60
        for kind, act in (("tok", "tokentx"), ("nat", "txlist")):
            s = st.setdefault(kind, {"legs": [], "page": 1, "done": False, "n": 0})
            while not s["done"]:
                if s["n"] >= EVM_PAGES:
                    s["done"], s["capped"] = True, True
                    break
                rows = self._es(chain, {"module": "account", "action": act, "address": H, "page": s["page"], "offset": ES_PAGE,
                                        "sort": "desc", "startblock": 0, "endblock": 9999999999})
                legs = es_native_legs(H, rows, chain) if kind == "nat" else es_token_legs(H, rows)
                seen9 = {leg_key(x) for x in s["legs"]}
                for x in legs:
                    if x["ts"] >= since and leg_key(x) not in seen9:
                        s["legs"].append(x)
                s["n"] += 1
                s["page"] += 1
                oldest = min((int(r.get("timeStamp") or 0) for r in rows if isinstance(r, dict)), default=0)
                if len(rows) < ES_PAGE or (oldest and oldest < since):
                    s["done"] = True
        legs = st["tok"]["legs"] + st["nat"]["legs"]
        evs = evm_events(H, chain, legs)
        self._price_events(evs)
        self.resolve_bridges(ent, evs)
        st["ev"] = evs
        st["capped"] = any(st[k].get("capped") for k in ("tok", "nat"))
        st["via"] = "etherscan"
        self._rpc_balances(ent, chain, H, legs)

    def _rpc_balances(self, ent, chain, H, legs):
        pad = "0x" + "0" * 24 + H[2:]
        bal = []
        b = self.t._evm(chain, "eth_getBalance", [H, "latest"])
        try:
            v = Decimal(int(b or "0x0", 16)) / Decimal(10 ** 18)
        except (TypeError, ValueError):
            v = Decimal(0)
        if v > 0:
            bal.append({"chain": chain, "token": "native", "sym": NATIVE.get(chain, "ETH"), "qty": str(v)})
        toks = []
        for x in legs:
            if x["token"] != "native" and x["token"] not in toks:
                toks.append(x["token"])
        for tok in toks[:8]:
            try:
                r = self.t._evm(chain, "eth_call", [{"to": tok, "data": "0x70a08231" + pad[2:]}, "latest"])
                q = Decimal(int(r or "0x0", 16)) / (Decimal(10) ** self.t.decimals(chain, tok))
            except xm.Budget:
                raise
            except Exception:
                continue
            if q > 0:
                bal.append({"chain": chain, "token": tok, "sym": self.sym_of(chain, tok) or short(tok), "qty": str(q)})
        now = int(time.time())
        for lg in bal:
            u, src = self.value(lg, now)
            if u is not None:
                lg["usd"], lg["ps"] = u, src
        ent.setdefault("bal", {})[chain] = {"t": now, "items": bal}

    def scan_evm_bs(self, ent, cand, chain):
        H = norm(cand["dest"])
        bs = self._bs(chain)
        st = ent.setdefault("evm", {}).setdefault(chain, {})
        since = cand["first"] - 60
        for kind, url0, fn in (("from", f"{bs}/api/v2/addresses/{H}/token-transfers?type=ERC-20&filter=from", "out"),
                               ("to", f"{bs}/api/v2/addresses/{H}/token-transfers?type=ERC-20&filter=to", "in"),
                               ("nat", f"{bs}/api/v2/addresses/{H}/transactions?filter=from", "out")):
            s = st.setdefault(kind, {"legs": [], "cur": None, "done": False, "n": 0})
            while not s["done"]:
                if s["n"] >= EVM_PAGES:
                    s["done"], s["capped"] = True, True
                    break
                url = url0 + ("&" + "&".join(f"{a}={b}" for a, b in s["cur"].items()) if isinstance(s.get("cur"), dict) else "")
                d = self.t._get(url) or {}
                items = d.get("items") or []
                legs = bs_native_legs(H, items, chain) if kind == "nat" else bs_token_legs(H, items, fn)
                s["legs"] += [x for x in legs if x["ts"] >= since]
                s["n"] += 1
                np_ = d.get("next_page_params")
                oldest = min((_bs_ts(it.get("timestamp")) for it in items), default=0)
                if not items or not isinstance(np_, dict) or not np_ or (oldest and oldest < since):
                    s["done"] = True
                else:
                    s["cur"] = np_
        legs = st["from"]["legs"] + st["to"]["legs"] + st["nat"]["legs"]
        evs = evm_events(H, chain, legs)
        self._price_events(evs)
        self.resolve_bridges(ent, evs)
        st["ev"] = evs
        st["capped"] = any(st[k].get("capped") for k in ("from", "to", "nat"))
        bal = []
        a = self.t._get(f"{bs}/api/v2/addresses/{H}") or {}
        try:
            cb = D(a.get("coin_balance")) / Decimal(10 ** 18)
        except (InvalidOperation, TypeError):
            cb = Decimal(0)
        if cb > 0:
            bal.append({"chain": chain, "token": "native", "sym": NATIVE.get(chain, "ETH"), "qty": str(cb),
                        **({"rate": a["exchange_rate"]} if a.get("exchange_rate") else {})})
        tk = self.t._get(f"{bs}/api/v2/addresses/{H}/tokens?type=ERC-20") or {}
        for it in tk.get("items") or []:
            t9 = it.get("token") or {}
            if t9.get("reputation") == "scam":
                continue
            try:
                q = D(it.get("value")) / (Decimal(10) ** int(t9.get("decimals") or 18))
            except (ValueError, TypeError, InvalidOperation):
                continue
            if q > 0:
                bal.append({"chain": chain, "token": norm(t9.get("address_hash") or t9.get("address")), "sym": t9.get("symbol") or "?",
                            "qty": str(q), **({"rate": t9["exchange_rate"]} if t9.get("exchange_rate") else {})})
        now = int(time.time())
        for lg in bal:
            u, src = self.value(lg, now)
            if u is not None:
                lg["usd"], lg["ps"] = u, src
        ent.setdefault("bal", {})[chain] = {"t": now, "items": bal}

    def _dec_safe(self, tok, chain="bsc"):
        try:
            return self.t.decimals(chain, tok)
        except xm.Budget:
            raise
        except Exception:
            return 18

    def scan_bsc(self, ent, cand):
        self.scan_rpcwin(ent, cand, "bsc", 10000, BSC_WINDOWS, BSC_SENDS, 0.45)

    def scan_rpcwin(self, ent, cand, chain, span, windows, sends_n, spb0):
        H = norm(cand["dest"])
        st = ent.setdefault("evm", {}).setdefault(chain, {"sends": {}, "legs": []})
        st.setdefault("sends", {})
        st.setdefault("legs", [])
        pad = "0x" + "0" * 24 + H[2:]
        sends = sorted([s for s in cand["sends"] if s.get("chain") == chain and s.get("tx")], key=lambda s: -float(s.get("usd") or 0))[:sends_n]
        seen = {(x["tx"], x["dir"], x["cp"], x["token"], x["qty"]) for x in st["legs"]}
        head = None
        for s in sends:
            k = norm(s["tx"])
            w = st["sends"].setdefault(k, {"block": None, "done": 0, "ts": int(s.get("ts") or 0)})
            if w["block"] is None:
                w["block"] = int(self.t.receipt(chain, s["tx"])["block"] or 0)
            if w["block"] and not w.get("spb"):
                if head is None:
                    head = int(self.t._evm(chain, "eth_blockNumber", []) or "0x0", 16)
                end = min(w["block"] + windows * span, head - 1)
                if end - w["block"] >= min(1000, span):
                    t_end = self.t.block_ts(chain, end)
                    w["spb"] = (t_end - w["ts"]) / float(end - w["block"]) if t_end and t_end > w["ts"] else spb0

            def ts_of(bn, w=w):
                return int(w["ts"] + (bn - w["block"]) * float(w.get("spb") or spb0))
            while w["done"] < windows and w["block"]:
                lo = w["block"] + w["done"] * span
                hi = lo + span - 1
                if head is None:
                    head = int(self.t._evm(chain, "eth_blockNumber", []) or "0x0", 16)
                if lo > head or (chain == "bsc" and hi > head):
                    break
                hi = min(hi, head)
                logs = []
                for tp in ([TR, pad], [TR, None, pad]):
                    logs += self.t._evm(chain, "eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "topics": tp}], logs=True) or []
                for x in log_legs(H, logs, lambda tok: self._dec_safe(tok, chain), lambda tok: self.sym_of(chain, tok) or short(tok), ts_of):
                    key = (x["tx"], x["dir"], x["cp"], x["token"], x["qty"])
                    if key not in seen:
                        seen.add(key)
                        st["legs"].append(x)
                if hi < lo + span - 1:
                    break
                w["done"] += 1
        evs = evm_events(H, chain, st["legs"])
        self._price_events(evs)
        self.resolve_bridges(ent, evs)
        st["ev"] = evs
        st["window"] = windows * span
        st["spb0"] = spb0
        if chain != "bsc":
            st["via"] = "rpc"
        self._rpc_balances(ent, chain, H, st["legs"])

    def scan(self, ent, cand):
        chains = cand["chains"] or (["sol"] if not cand["dest"].startswith("0x") else [])
        for ch in chains:
            if ch == "sol":
                self.scan_sol(ent, cand)
            elif ch == "bsc":
                self.scan_bsc(ent, cand)
            elif self._bs(ch) and not self._bs_dead(ch):
                try:
                    self.scan_evm_bs(ent, cand, ch)
                except urllib.error.HTTPError as e:
                    if e.code != 403:
                        raise
                    self.c.setdefault("_memo", {}).setdefault("bs403", {})[ch] = int(time.time())
                    (ent.get("evm") or {}).pop(ch, None)
                    self._scan_alt(ent, cand, ch)
            elif self._alt(ch):
                self._scan_alt(ent, cand, ch)
            else:
                ent.setdefault("skip", [])
                if ch not in ent["skip"]:
                    ent["skip"].append(ch)


def run_once(cfg, state_dir, cands, budget=40, log=None, px=None, sleep=0.35, sym_of=None, limit=1):
    cache = load_cache(state_dir)
    done = []
    off9 = set((cfg or {}).get("_disabled_chains") or ())
    off9.update(c9 for c9, cc9 in ((cfg or {}).get("chains") or {}).items() if isinstance(cc9, dict) and not common.chain_enabled(c9, cc9))
    for cand in cands[:limit]:
        a = cand["dest"]
        if off9 and off9.intersection(cand.get("chains") or ()):
            done.append((a, "off", 0))
            continue
        ent = cache["dest"].get(a) or {}
        if ent.get("fp") != cand["fp"] or ent.get("status") in ("ok", "partial"):
            keep = {"sol": ent.get("sol")} if ent.get("sol") else {}
            if keep.get("sol"):
                keep["sol"]["capped"] = None
            ent = dict(keep, calls=0)
        ent.update({"fp": cand["fp"], "first": cand["first"], "chains": cand["chains"], "status": "running"})
        ent.setdefault("t0", int(time.time()))
        cache["dest"][a] = ent
        sc = Scanner(cfg, cache, px=px, budget=max(1, min(budget, PER_DEST_CALLS - int(ent.get("calls") or 0))), sleep=sleep, log=log, sym_of=sym_of)
        st = "ok"
        try:
            if int(ent.get("calls") or 0) >= PER_DEST_CALLS:
                raise xm.Budget()
            sc.scan(ent, cand)
            capped = bool((ent.get("sol") or {}).get("capped")) or any(v.get("capped") for v in (ent.get("evm") or {}).values())
            st = "partial" if capped else "ok"
        except xm.Paused as e:
            st = "paused"
            ent["err"] = common.safe_err(e)[:200]
        except xm.Budget:
            st = "partial" if int(ent.get("calls") or 0) + sc.calls >= PER_DEST_CALLS else "budget"
        except Exception as e:
            st = "error"
            ent["err"] = common.safe_err(e)[:200]
            (log or (lambda *a: None))(f"flow-trace {short(a)}: {e}")
        ent["calls"] = int(ent.get("calls") or 0) + sc.calls
        ent["status"] = st
        ent["rt"] = int(time.time())
        if st in ("ok", "partial"):
            ent["t"] = int(time.time())
            ent.pop("err", None)
        save_cache(state_dir, cache)
        done.append((a, st, sc.calls))
    return done


def all_events(ent):
    ev = []
    for sig_ev in ((ent.get("sol") or {}).get("ev") or {}).values():
        ev += sig_ev
    for ch, st in (ent.get("evm") or {}).items():
        ev += st.get("ev") or []
    ev.sort(key=lambda e: int(e.get("ts") or 0))
    return ev


def _usd(lg, px_now):
    if lg.get("usd") is not None:
        return float(lg["usd"]), bool(lg.get("apx"))
    q = float(D(lg.get("qty")))
    p = px_now(lg.get("chain"), lg.get("token"), lg.get("sym")) if px_now else None
    if p:
        return q * float(p), True
    if lg.get("rate"):
        try:
            return q * float(lg["rate"]), True
        except (TypeError, ValueError):
            pass
    return None, True


PROTO_KO = {"relay": "Relay", "debridge": "deBridge", "wormhole": "Wormhole", "wormhole_ntt": "Wormhole NTT", "cctp": "CCTP",
            "mayan": "Mayan", "ccip": "Chainlink CCIP", "across": "Across", "stargate": "Stargate", "?": "브릿지"}


_GSFX = re.compile(r"#\d+$")


def disp_sym(sym) -> str:
    return _GSFX.sub("", str(sym or ""))


def spam_token(e, spam_tok=frozenset()) -> bool:
    tok = e.get("token")
    if not tok or tok == "native":
        return False
    ch = e.get("chain")
    if spamguard.is_genuine(ch, tok):
        return False
    if spam_tok and (ch, norm(tok)) in spam_tok:
        return True
    s = disp_sym(e.get("sym"))
    return bool(s and (spamguard.impostor_of(s) or spamguard.odd_symbol(s)))


def spoof(e, u, look, spam_tok=frozenset()):
    if u is not None:
        return False
    sym = str(e.get("sym") or "")
    return (not sym.isascii()) or bool(look(e.get("cp") or "")) or spam_token(e, spam_tok)


def mine_score(ev):
    kinds = {e["k"] for e in ev}
    n = len(kinds)
    strong = bool(kinds & {"back", "exch_in", "prior", "roundtrip"})
    lvl = "high" if n >= 2 and strong else ("mid" if n >= 1 else "none")
    return {"level": lvl, "n": n, "ev": ev}


def evidence(addr, ctx, since=0, is_dest=False):
    if is_burn(addr):
        return []
    ev = []
    fm = (ctx.get("from_mine") or {}).get(addr)
    if fm and not is_dest:
        ev.append({"k": "from_mine", "t": f"내 등록 지갑에서 직접 받음 {fm['n']}건 ${fm['usd']:,.0f}"})
    wd = (ctx.get("wd_in") or {}).get(addr)
    if wd:
        ev.append({"k": "wd_in", "t": f"내 거래소 계정 출금을 받음 {wd['n']}건" + (f" ({', '.join(wd.get('exchanges') or [])})" if wd.get("exchanges") else "")})
    bk = [x for x in (ctx.get("back") or {}).get(addr) or [] if int(x.get("ts") or 0) >= since]
    if bk:
        ev.append({"k": "back", "t": f"나중에 내 지갑으로 보냄 {len(bk)}건 ${sum(float(x.get('usd') or 0) for x in bk):,.0f}"})
    ei = [x for x in (ctx.get("exch_in") or {}).get(addr) or [] if int(x.get("ts") or 0) >= since]
    if ei:
        ev.append({"k": "exch_in", "t": f"내 거래소 계정에 입금 {len(ei)}건" + (f" ${sum(float(x.get('usd') or 0) for x in ei):,.0f}" if any(x.get('usd') for x in ei) else "")})
    w_from = set((fm or {}).get("wallets") or ())
    w_back = {x.get("wallet") for x in (ctx.get("back") or {}).get(addr) or [] if x.get("wallet")}
    if w_from and w_back and len(w_from | w_back) >= 2:
        ev.append({"k": "multi", "t": f"등록 지갑 {len(w_from | w_back)}개와 양방향(보냄 {len(w_from)} · 받음 {len(w_back)})"})
    rw = (ctx.get("rows") or {}).get(addr) or {}
    if rw.get("priorUsd"):
        ev.append({"k": "prior", "t": f"먼저 나에게 자금을 댐 ${float(rw['priorUsd']):,.0f}"})
    if rw.get("returnKind") == "full":
        ev.append({"k": "roundtrip", "t": "받은 만큼 이상 내 지갑으로 되돌려보냄(왕복)"})
    return ev


_WRAP = {"WETH": "ETH", "WBNB": "BNB", "WSOL": "SOL", "WPOL": "POL", "WMATIC": "POL", "MATIC": "POL", "WAVAX": "AVAX"}


def _tokkey(sym) -> str:
    s0 = str(sym or "").upper()
    s0 = s0[:-2] if s0.endswith(".E") else s0
    return _WRAP.get(s0, s0)


def account(row, ent, ctx, px_now=None, max_recips=12):
    a = row["address"]
    first = int(row.get("firstTs") or 0)
    sent = float(row.get("usdAtSend") or 0) or float(row.get("usdNow") or 0)
    sent = max(0.0, sent - float(row.get("matchedUsd") or 0))
    direct = float(row.get("returnedUsd") or 0)
    direct_tx = {norm(x.get("tx")) for x in row.get("returned") or []}
    grp_map = ctx.get("grp") or {}

    def _grp(sym, chain=None, token=None):
        g0 = grp_map.get((chain, norm(token))) if (chain and token) else None
        s0 = str(g0 or sym or "").upper()
        return s0[:-2] if s0.endswith(".E") else s0

    dpool, legacy_tx = [], set()
    for x9 in row.get("returned") or []:
        if not x9.get("tx"):
            continue
        if x9.get("qty") is None or not x9.get("sym"):
            legacy_tx.add(norm(x9["tx"]))
            continue
        dpool.append({"tx": norm(x9["tx"]), "w": norm(x9.get("wallet")) if x9.get("wallet") else None, "ex": None,
                      "g": _grp(x9.get("sym")), "left": float(D(x9.get("qty")))})
    cpool = []
    for own9, l9 in [(True, x9) for x9 in row.get("links") or []] + [(False, x9) for x9 in row.get("linkedAway") or []]:
        if not (isinstance(l9, dict) and l9.get("tx") and ((l9.get("kind") == "refund" and l9.get("st") == "ok")
                                                            or (l9.get("kind") == "tokens" and l9.get("st") == "applied"))):
            continue
        w9 = str(l9.get("where") or "")
        if own9 and l9.get("kind") == "refund" and not w9.startswith("ex:"):
            continue
        cpool.append({"tx": norm(l9["tx"]), "w": norm(w9[2:]) if w9.startswith("w:") else None, "ex": w9[3:] if w9.startswith("ex:") else None,
                      "g": _grp(l9.get("sym")), "left": float(D(l9.get("qty")))})

    def _take(pool, tx, g, qty, to=None, ex=None):
        tx, want = norm(tx), max(0.0, float(D(qty)))
        got = 0.0
        for c9 in pool:
            if want - got <= 1e-12:
                break
            if c9["left"] <= 1e-12 or c9["tx"] != tx or c9["g"] != g:
                continue
            if c9["w"] is not None and (to is None or c9["w"] != norm(to)):
                continue
            if c9["ex"] is not None and (ex is None or (ex != "?" and c9["ex"] != ex)):
                continue
            if c9["w"] is None and c9["ex"] is None and to is None and ex is None:
                continue
            t9 = min(c9["left"], want - got)
            c9["left"] -= t9
            got += t9
        return got

    def _rest(x9, qkey, taken):
        q9 = float(D(x9.get(qkey)))
        if taken <= 1e-12:
            return x9
        if q9 <= 0 or taken >= q9 * (1 - 1e-9):
            return None
        f9 = (q9 - taken) / q9
        return dict(x9, usd=(float(x9["usd"]) * f9 if x9.get("usd") is not None else None), **{qkey: q9 - taken})
    direct_full = int(row.get("returnedN") or 0) <= len(row.get("returned") or [])
    mine, exch, bridges = ctx.get("mine") or set(), ctx.get("exch") or {}, ctx.get("bridges") or {}
    look = ctx.get("lookalike") or (lambda x: False)
    spam_tok = ctx.get("spam_tok") or frozenset()
    out = {"status": (ent or {}).get("status") or "queued", "sent": round(sent, 2), "scannedAt": (ent or {}).get("t"),
           "notes": [], "recips": [], "swaps": {"n": 0, "sold": [], "bought": []}}
    ev = all_events(ent or {})
    hid_n, hid = 0, []

    def _hide(e9, u9, token_only=False):
        nonlocal hid_n
        if not ((u9 is None and spam_token(e9, spam_tok)) if token_only else spoof(e9, u9, look, spam_tok)):
            return False
        hid_n += 1
        hid.append({"ts": int(e9.get("ts") or 0), "tx": e9.get("tx"), "chain": e9.get("chain"), "sym": disp_sym(e9.get("sym")) or "?",
                    "qty": float(D(e9.get("qty"))), "dir": e9.get("kind"), "cp": e9.get("cp") or "?"})
        if len(hid) > 2 * HID_KEEP:
            hid.sort(key=lambda x: -x["ts"])
            del hid[HID_KEEP:]
        return True
    rec = {}
    swaps_sold, swaps_bought = {}, {}
    mixed, mixed_n, unpriced = 0.0, 0, 0
    exch_usd, extra_direct, bridged_back = 0.0, 0.0, 0.0
    for e in ev:
        if e["kind"] == "swap":
            legs9 = {"sold": [], "bought": []}
            for side in ("sold", "bought"):
                for lg in e.get(side) or []:
                    hl9 = dict(lg, kind="out" if side == "sold" else "in", ts=e.get("ts"), tx=e.get("tx"), chain=lg.get("chain") or e.get("chain"), cp=None)
                    if not _hide(hl9, _usd(lg, px_now)[0], token_only=True):
                        legs9[side].append(lg)
            if not (legs9["sold"] or legs9["bought"]):
                continue
            out["swaps"]["n"] += 1
            for side, acc in (("sold", swaps_sold), ("bought", swaps_bought)):
                for lg in legs9[side]:
                    u, _ap = _usd(lg, px_now)
                    k = (lg.get("sym") or "?")
                    s9 = acc.setdefault(k, {"sym": k, "qty": 0.0, "usd": 0.0, "n": 0})
                    s9["qty"] += float(D(lg.get("qty"))); s9["usd"] += u or 0.0; s9["n"] += 1
            continue
        u, approx = _usd(e, px_now)
        if _hide(e, u):
            continue
        if e["kind"] == "in":
            cp = e.get("cp") or "?"
            if cp not in mine and u is not None and u >= DUST_USD:
                mixed += u
                mixed_n += 1
            continue
        cp = e.get("cp") or "?"
        brg = e.get("br") or {}
        if brg.get("to"):
            cp = norm(brg["to"])
        if u is not None and u < DUST_USD:
            continue
        g9e = _grp(e.get("sym"), e.get("chain"), e.get("token"))
        q9e = float(D(e.get("qty")))
        if cp in mine and u is None:
            new9 = 1.0
        elif cp in mine:
            tk9 = q9e if norm(e.get("tx")) in legacy_tx else _take(dpool, e.get("tx"), g9e, q9e, to=cp)
            tk9 += _take(cpool, e.get("tx"), g9e, q9e - tk9, to=cp) if q9e - tk9 > 1e-12 else 0.0
            new9 = 0.0 if q9e <= 0 or tk9 >= q9e * (1 - 1e-9) else (q9e - tk9) / q9e
        else:
            new9 = 1.0
            if cpool and exch.get(cp):
                e2 = _rest(e, "qty", _take(cpool, e.get("tx"), g9e, q9e, ex="?"))
                if e2 is None:
                    continue
                if e2 is not e:
                    e = e2
                    u, approx = _usd(e, px_now)
        if cp in mine and new9 > 0 and int(e.get("ts") or 0) >= first:
            if brg.get("to"):
                bridged_back += (u or 0.0) * new9
            elif direct_full:
                extra_direct += (u or 0.0) * new9
        if u is None:
            unpriced += 1
        r9 = rec.setdefault(cp, {"addr": cp, "chains": set(), "coins": {}, "usd": 0.0, "n": 0, "first": e["ts"], "last": e["ts"],
                                 "txs": [], "contract": bool(e.get("cpc")) and not brg.get("to"), "name": e.get("cpn"), "approx": False,
                                 "bridge": None})
        r9["chains"].add(brg.get("dst") or e.get("chain"))
        if brg.get("to"):
            r9["bridge"] = {"proto": brg.get("proto"), "name": PROTO_KO.get(brg.get("proto"), brg.get("proto")),
                            "src": e.get("chain"), "dst": brg.get("dst"), "via": e.get("cp")}
        elif e.get("bp") and not r9["bridge"]:
            r9["bridge"] = {"proto": e["bp"], "name": PROTO_KO.get(e["bp"], e.get("cpn") or "브릿지"), "src": e.get("chain"), "dst": None,
                            "via": e.get("cp")}
        c9 = r9["coins"].setdefault(e.get("sym") or "?", {"sym": e.get("sym") or "?", "qty": 0.0, "usd": 0.0})
        c9["qty"] += float(D(e.get("qty"))); c9["usd"] += u or 0.0
        r9["usd"] += u or 0.0; r9["n"] += 1; r9["approx"] = r9["approx"] or approx
        r9["first"] = min(r9["first"], e["ts"]); r9["last"] = max(r9["last"], e["ts"])
        if len(r9["txs"]) < 6:
            r9["txs"].append({"ts": e["ts"], "tx": e["tx"], "chain": e.get("chain"), "sym": e.get("sym"), "qty": float(D(e.get("qty"))),
                              "usd": round(u, 2) if u is not None else None})
    back = ctx.get("back") or {}
    exch_in = ctx.get("exch_in") or {}
    hop_usd = 0.0
    recips = []
    for cp, r9 in rec.items():
        if cp == norm(a):
            kind, lab = "self", "이 주소 자신 · 다른 체인으로 브릿지"
        elif cp in mine:
            kind, lab = "mine", (ctx.get("alias") or {}).get(cp) or "내 지갑"
        elif cp in exch:
            kind, lab = "exchange", exch[cp]
            exch_usd += r9["usd"]
        elif is_burn(cp):
            kind, lab = "burn", "발행·소각 주소 — 누구의 지갑도 아님"
        elif cp in bridges or (r9.get("bridge") and not r9["bridge"].get("dst")):
            kind, lab = "bridge", bridges.get(cp) or f"브릿지 ({(r9.get('bridge') or {}).get('name') or '?'}) — 도착지 모름"
        elif r9["contract"]:
            kind, lab = "contract", r9.get("name") or "컨트랙트"
        elif cp == "?":
            kind, lab = "unknown", "받는 주소 특정 불가"
        else:
            kind, lab = "eoa", "모르는 주소"
        via = 0.0
        vb = [x2 for x2 in (_rest(x, "qty", _take(cpool, x.get("tx"), _grp(x.get("sym")), x.get("qty"), to=x.get("wallet") or "?"))
                            for x in (back.get(cp) or []) if int(x.get("ts") or 0) >= r9["first"] and norm(x.get("tx")) not in direct_tx)
              if x2 is not None]
        vx = [x2 for x2 in (_rest(x, "qty", _take(cpool, x.get("txn"), _grp(x.get("sym")), x.get("qty"), ex=x.get("ex") or "?"))
                            for x in (exch_in.get(cp) or []) if int(x.get("ts") or 0) >= r9["first"]) if x2 is not None]
        if kind in ("eoa", "contract", "unknown") and (vb or vx):
            via = min(r9["usd"], sum(float(x.get("usd") or 0) for x in vb + vx))
            hop_usd += via
        sc = mine_score(evidence(cp, ctx, since=0)) if kind == "eoa" else {"level": "none", "n": 0, "ev": []}
        if kind == "eoa" and sc["level"] == "high":
            kind9, lab9 = "lookmine", "내 지갑일 가능성 높음"
        else:
            kind9, lab9 = kind, lab
        recips.append({"addr": cp, "kind": kind9, "base": kind, "label": lab9 if kind9 == "lookmine" else lab,
                       "chains": sorted(c for c in r9["chains"] if c), "usd": round(r9["usd"], 2), "n": r9["n"],
                       "first": r9["first"], "last": r9["last"], "approx": r9["approx"],
                       "coins": sorted(({"sym": c["sym"], "qty": round(c["qty"], 8), "usd": round(c["usd"], 2)} for c in r9["coins"].values()),
                                       key=lambda c: -c["usd"]),
                       "txs": sorted(r9["txs"], key=lambda t: -int(t["ts"] or 0)),
                       "via": round(via, 2), "viaN": len(vb) + len(vx), "score": sc, "bridge": r9.get("bridge"),
                       "registerable": kind9 == "lookmine" or (kind == "eoa" and sc["level"] == "mid")})
    recips.sort(key=lambda r: -r["usd"])
    still_items = []
    for ch, b in ((ent or {}).get("bal") or {}).items():
        for lg in b.get("items") or []:
            u, approx = _usd(lg, px_now)
            if u is None or u < DUST_USD:
                continue
            still_items.append({"chain": ch, "sym": lg.get("sym"), "qty": float(D(lg.get("qty"))), "usd": round(u, 2), "approx": approx})
    still_items.sort(key=lambda x: -x["usd"])
    still = sum(x["usd"] for x in still_items)
    seen_tx = {norm(e.get("tx")) for e in ev}
    exch_extra = [x2 for x2 in (_rest(x, "qty", _take(cpool, x.get("txn"), _grp(x.get("sym")), x.get("qty"), ex=x.get("ex") or "?"))
                                for x in (exch_in.get(a) or []) if int(x.get("ts") or 0) >= first and norm(x.get("txn")) not in seen_tx)
                  if x2 is not None]
    exch_usd += sum(float(x.get("usd") or 0) for x in exch_extra)
    returned = direct + extra_direct + exch_usd + hop_usd + bridged_back
    ELSE = ("eoa", "contract", "unknown", "bridge", "self", "burn")
    elsewhere = sum(r["usd"] - r["via"] for r in recips if r["base"] in ELSE)
    else_mine = sum(r["usd"] - r["via"] for r in recips if r["kind"] == "lookmine")
    left = max(0.0, sent - returned)
    still_tok = still
    if mixed_n and (row.get("tokens") or out["swaps"]["n"]):
        capq = {}
        for t9 in row.get("tokens") or []:
            if isinstance(t9, dict) and t9.get("sym") and not t9.get("phantom"):
                k9 = _tokkey(t9["sym"])
                capq[k9] = capq.get(k9, 0.0) + max(0.0, float(t9.get("qty") or 0))
        for k9, v9 in swaps_bought.items():
            capq[_tokkey(k9)] = capq.get(_tokkey(k9), 0.0) + max(0.0, float(v9.get("qty") or 0))
        still_tok = 0.0
        for x9 in still_items:
            q9, c9 = float(x9.get("qty") or 0), capq.get(_tokkey(x9.get("sym")), 0.0)
            still_tok += x9["usd"] if q9 <= c9 else (x9["usd"] * c9 / q9 if q9 > 0 else 0.0)
    still_m = min(still, still_tok, left)
    else_m = min(max(0.0, elsewhere), max(0.0, left - still_m))
    capped = still - still_m > 0.5 or max(0.0, elsewhere) - else_m > 0.5
    unexplained = sent - returned - still_m - else_m
    out.update({
        "returned": {"usd": round(returned, 2), "direct": round(direct + extra_direct, 2), "exchange": round(exch_usd, 2),
                     "bridge": round(bridged_back, 2),
                     "exchangeN": sum(1 for r in recips if r["base"] == "exchange") + len(exch_extra), "hop": round(hop_usd, 2)},
        "still": {"usd": round(still_m, 2), "items": still_items[:8], "all": round(still, 2)},
        "elsewhere": {"usd": round(else_m, 2), "lookMine": round(max(0.0, min(else_mine, else_m)), 2), "all": round(max(0.0, elsewhere), 2),
                      "n": sum(1 for r in recips if r["base"] in ELSE and r["usd"] - r["via"] >= DUST_USD)},
        "capped": capped,
        "unexplained": round(unexplained, 2),
        "net": round(sent - returned - (0.0 if capped else still_m), 2),
        "held": bool(capped),
        "mixedIn": {"usd": round(mixed, 2), "n": mixed_n},
        "unpriced": unpriced,
        "recips": [r for r in recips if r["base"] != "mine"][:max_recips],
        "mineN": sum(1 for r in recips if r["base"] == "mine"),
        "spoofHidden": {"n": hid_n, "items": sorted(hid, key=lambda x: -x["ts"])[:HID_KEEP]},
    })
    out["swaps"]["sold"] = sorted(({**v, "qty": round(v["qty"], 8), "usd": round(v["usd"], 2)} for v in swaps_sold.values()), key=lambda x: -x["usd"])[:6]
    out["swaps"]["bought"] = sorted(({**v, "qty": round(v["qty"], 8), "usd": round(v["usd"], 2)} for v in swaps_bought.values()), key=lambda x: -x["usd"])[:6]
    out["score"] = mine_score(evidence(a, ctx, since=first, is_dest=True))
    if ent:
        if (ent.get("sol") or {}).get("capped"):
            out["notes"].append("솔라나 조회 상한에 닿아 일부만 읽었어요")
        for ch, st in (ent.get("evm") or {}).items():
            if st.get("capped"):
                out["notes"].append(f"{CHAIN_KO.get(ch, ch)} 조회 상한에 닿아 최근 일부만 읽었어요")
            if ch == "bsc" and st.get("window"):
                out["notes"].append("BSC 는 공개 노드 한도로 보낸 뒤 약 10시간 안의 이동만 읽어요")
            elif st.get("window"):
                h9 = max(1, round(float(st["window"]) * float(st.get("spb0") or 2.0) / 3600))
                out["notes"].append(f"{CHAIN_KO.get(ch, ch)} 는 탐색기가 막혀 공개 노드로 보낸 뒤 약 {h9}시간 안의 토큰 이동만 읽어요")
        for ch in ent.get("skip") or []:
            out["notes"].append(f"{CHAIN_KO.get(ch, ch)} 는 공개 탐색기가 없어 이 주소 활동을 못 읽어요")
        for ch in ent.get("blocked") or []:
            out["notes"].append(f"{CHAIN_KO.get(ch, ch)} 는 공개 탐색기가 막혀(접속 차단) 이번엔 이 주소 활동을 못 읽었어요 — 다음 재조회 때 다시")
        if unpriced:
            out["notes"].append(f"가격을 모르는 토큰 전송 {unpriced}건은 금액에서 빠졌어요")
    if mixed > max(100.0, sent * 0.1):
        out["notes"].append(f"이 주소는 다른 곳에서도 ${mixed:,.0f} 받았어요 — 금액이 섞여 있어 추정치예요")
    return out
