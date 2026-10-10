"""Cross-chain bridge transfer matching."""
import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import netpace

TR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40
CACHE_NAME = "xchain_cache.json"
CACHE_V = 1
MAX_DEPTH = 3
GATE_USD = Decimal("50")
SOL_SPEND_MIN = Decimal("0.02")
RETRY_SEC = 24 * 3600
WAIT_SEC = 1800
WAIT_MAX = 48 * 3600
REV_HOPFIFO = "hopfifo_v1"
HOP_MAX_NONCE = 5000
ACCT_TTL = 30 * 86400
REV_HOPX = "hopx_1004"
REV_HOPSCAN = "hopscan_v1"
REV_HOPOPEN = "hopopen_1007"
BUDGET_RETRY_SEC = 3600
MAX_PAGES = int(os.environ.get("XCHAIN_MAX_PAGES", "60"))
MAX_WINDOWS = int(os.environ.get("XCHAIN_MAX_WINDOWS", "400"))
SOL_SIG_PAGE, SOL_SIG_PAGES = 100, 3
SOL_SIG_CHUNKS = int(os.environ.get("XCHAIN_SOL_CHUNKS", "10"))
CLUS_PAGES_TT = int(os.environ.get("XCHAIN_CLUS_PAGES", "40"))
CLUS_PAGES_TX = int(os.environ.get("XCHAIN_CLUS_TX_PAGES", "20"))
CHAIN_KO = {"sol": "솔라나", "eth": "이더리움", "bsc": "BSC", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism",
            "polygon": "Polygon", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis", "robinhood": "Robinhood", "arc": "Arc"}
NATIVE = {"sol": "SOL", "eth": "ETH", "base": "ETH", "arbitrum": "ETH", "optimism": "ETH", "scroll": "ETH", "zksync": "ETH",
          "bsc": "BNB", "polygon": "POL", "gnosis": "XDAI", "robinhood": "ETH", "arc": "USDC"}
import common as _cm9
_cm9.fill_chain_table(CHAIN_KO)
_cm9.fill_chain_table(NATIVE, 1)
WRAPPED = {"eth": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "base": "0x4200000000000000000000000000000000000006",
           "optimism": "0x4200000000000000000000000000000000000006", "arbitrum": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
           "bsc": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "polygon": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270"}
WSOL = "So11111111111111111111111111111111111111112"
REL_BRIDGE = Decimal("0.01")
REL_SOLVER = Decimal("0.03")
ABS_STABLE = Decimal("1")
WINDOW = 3600
WINDOW_BRIDGE = 6 * 3600


def D(x) -> Decimal:
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def norm(a) -> str:
    a = str(a or "")
    return a.lower() if a.startswith("0x") else a


def _r(x) -> str:
    return str(D(x).quantize(Decimal("0.000001")))


def short(a) -> str:
    a = str(a or "")
    return a if len(a) < 12 else f"{a[:6]}…{a[-4:]}"


def load_seed(base_dir):
    import common as _cm8
    bd = base_dir if os.path.exists(os.path.join(base_dir, "seed", "xchain_bridges.json")) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    s = _cm8.seed_json("xchain_bridges.json", {}, base_dir=bd)
    s = s if isinstance(s, dict) else {}
    s["evm_contracts"] = {norm(k): v for k, v in (s.get("evm_contracts") or {}).items()}
    s["solvers"] = {norm(k): v for k, v in (s.get("solvers") or {}).items()}
    return s


def label(proto, src, dst, seed=None) -> str:
    nm = ((seed or {}).get("proto_names") or {}).get(proto) or (proto or "?")
    return f"브릿지 ({nm}) {CHAIN_KO.get(src, src or '?')} → {CHAIN_KO.get(dst, dst or '?')}"


def compact_sol_tx(t):
    if not isinstance(t, dict) or not t.get("meta"):
        return None
    m, msg = t["meta"], t["transaction"]["message"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    for k in ((m.get("loadedAddresses") or {}).get("writable") or []) + ((m.get("loadedAddresses") or {}).get("readonly") or []):
        keys.append(k)
    progs = set()
    for ins in msg.get("instructions") or []:
        progs.add(ins.get("programId") or (keys[ins["programIdIndex"]] if "programIdIndex" in ins else None))
    for ii in m.get("innerInstructions") or []:
        for ins in ii.get("instructions") or []:
            progs.add(ins.get("programId") or (keys[ins["programIdIndex"]] if "programIdIndex" in ins else None))
    progs.discard(None)

    def tb(lst):
        return [{"i": b["accountIndex"], "mint": b["mint"], "owner": b.get("owner"),
                 "amt": (b.get("uiTokenAmount") or {}).get("amount", "0"), "dec": (b.get("uiTokenAmount") or {}).get("decimals", 0)}
                for b in lst or []]
    signers = [k["pubkey"] for k in msg.get("accountKeys") or [] if isinstance(k, dict) and k.get("signer")]
    return {"ts": t.get("blockTime"), "slot": t.get("slot"), "err": m.get("err") is not None, "fee": m.get("fee") or 0,
            "keys": keys, "pre": m.get("preBalances") or [], "post": m.get("postBalances") or [],
            "ptb": tb(m.get("preTokenBalances")), "qtb": tb(m.get("postTokenBalances")),
            "progs": sorted(progs), "signers": signers,
            "logs": [ln for ln in (m.get("logMessages") or []) if "Instruction:" in ln][:80]}


def sol_owner_deltas(ct, owner):
    out = {}
    pre = {b["i"]: b for b in ct["ptb"]}
    post = {b["i"]: b for b in ct["qtb"]}
    for i in set(pre) | set(post):
        b = post.get(i) or pre.get(i)
        if b.get("owner") != owner:
            continue
        a = int((pre.get(i) or {}).get("amt") or 0)
        z = int((post.get(i) or {}).get("amt") or 0)
        if a != z:
            out[b["mint"]] = out.get(b["mint"], Decimal(0)) + Decimal(z - a) / (Decimal(10) ** int(b.get("dec") or 0))
    sol = Decimal(0)
    if owner in ct["keys"]:
        i = ct["keys"].index(owner)
        if i < len(ct["pre"]) and i < len(ct["post"]):
            sol = Decimal(ct["post"][i] - ct["pre"][i]) / Decimal(10 ** 9)
    return out, sol


def sol_owner_pre(ct, owner, mint) -> Decimal:
    tot = Decimal(0)
    for b in ct.get("ptb") or []:
        if b.get("owner") == owner and b.get("mint") == mint:
            tot += Decimal(int(b.get("amt") or 0)) / (Decimal(10) ** int(b.get("dec") or 0))
    return tot


def sol_counterparty(ct, mint, owner):
    pre = {b["i"]: b for b in ct["ptb"]}
    post = {b["i"]: b for b in ct["qtb"]}
    best, amt = None, 0
    for i in set(pre) | set(post):
        b = post.get(i) or pre.get(i)
        if b["mint"] != mint or b.get("owner") in (None, owner):
            continue
        d = int((post.get(i) or {}).get("amt") or 0) - int((pre.get(i) or {}).get("amt") or 0)
        if d < amt:
            best, amt = b.get("owner"), d
    return best


def sol_token_account(ct, mint, owner):
    for b in ct["ptb"] + ct["qtb"]:
        if b["mint"] == mint and b.get("owner") == owner:
            return ct["keys"][b["i"]] if b["i"] < len(ct["keys"]) else None
    return None


def sol_bridge_proto(ct, seed):
    progs = seed.get("sol_programs") or {}
    for p in ct["progs"]:
        if p in progs:
            return progs[p]["proto"]
    for ln in ct["logs"]:
        for mk, proto in (seed.get("sol_log_markers") or {}).items():
            if mk in ln:
                return proto
    for p in ct["progs"]:
        if p.startswith("ntt") or p.startswith("NTT"):
            return "wormhole_ntt"
    return None


def sol_is_lp(ct, seed):
    lp = seed.get("sol_lp_programs") or {}
    if not any(p in lp for p in ct["progs"]):
        return False
    return any(mk in ln for ln in ct["logs"] for mk in (seed.get("sol_lp_markers") or []))


def sol_solver(ct, seed):
    for s in ct.get("signers") or []:
        if norm(s) in (seed.get("solvers") or {}):
            return (seed["solvers"][norm(s)] or {}).get("proto")
    return None


def compact_receipt(r, t):
    if not isinstance(r, dict):
        return None
    logs = []
    for lg in r.get("logs") or []:
        tp = lg.get("topics") or []
        if tp and (tp[0] == TR and len(tp) == 3 or tp[0].startswith("0x6eb224fb")):
            logs.append({"a": norm(lg.get("address")), "t": tp, "d": lg.get("data") or "0x"})
    return {"block": int(r["blockNumber"], 16) if r.get("blockNumber") else None, "from": norm(r.get("from")),
            "to": norm(r.get("to")), "status": r.get("status"), "value": int((t or {}).get("value") or "0x0", 16),
            "logs": logs}


def evm_owner_deltas(cr, owner):
    owner = norm(owner)
    out = {}
    for lg in cr["logs"]:
        if lg["t"][0] != TR:
            continue
        f = "0x" + lg["t"][1][26:]
        to = "0x" + lg["t"][2][26:]
        try:
            v = int(lg["d"], 16)
        except ValueError:
            continue
        if f == owner:
            out[lg["a"]] = out.get(lg["a"], 0) - v
        if to == owner:
            out[lg["a"]] = out.get(lg["a"], 0) + v
    return out


def evm_token_senders(cr, token, owner):
    owner = norm(owner)
    s = []
    for lg in cr["logs"]:
        if lg["t"][0] == TR and lg["a"] == norm(token) and "0x" + lg["t"][2][26:] == owner:
            s.append("0x" + lg["t"][1][26:])
    return s


def wh_emitters(cr):
    out = []
    for lg in cr["logs"]:
        if lg["t"][0].startswith("0x6eb224fb") and len(lg["t"]) >= 2:
            try:
                out.append(("0x" + lg["t"][1][26:], int(lg["d"][2:66], 16)))
            except ValueError:
                pass
    return out


def parse_ws_op(op, seed):
    if not isinstance(op, dict):
        return None
    wc = seed.get("wormhole_chain_ids") or {}
    sc, tc = op.get("sourceChain") or {}, op.get("targetChain") or {}
    sp = (op.get("content") or {}).get("standarizedProperties") or {}
    apps = sp.get("appIds") or []
    proto = "wormhole_ntt" if "NATIVE_TOKEN_TRANSFER" in apps else ("cctp" if any("CCTP" in a for a in apps) else
                                                                    ("mayan" if any("MAYAN" in a for a in apps) else "wormhole"))
    return {"id": op.get("id"), "proto": proto,
            "src_chain": wc.get(str(sc.get("chainId") or sp.get("fromChain"))), "src_tx": norm((sc.get("transaction") or {}).get("txHash")),
            "src_from": norm(sc.get("from")), "src_ts": sc.get("timestamp"),
            "dst_chain": wc.get(str(tc.get("chainId") or sp.get("toChain"))), "dst_tx": norm((tc.get("transaction") or {}).get("txHash")),
            "to": norm(sp.get("toAddress")), "token_chain": wc.get(str(sp.get("tokenChain"))), "token": norm(sp.get("tokenAddress")),
            "amount": (op.get("data") or {}).get("tokenAmount"), "usd": (op.get("data") or {}).get("usdAmount")}


def parse_dln_order(o, src_tx, seed):
    dc = seed.get("debridge_chain_ids") or {}
    st = o.get("orderStruct") or {}
    give, take = st.get("giveOffer") or {}, st.get("takeOffer") or {}
    return {"id": o.get("orderId"), "proto": "debridge", "src_chain": dc.get(str(give.get("chainId"))), "src_tx": norm(src_tx),
            "src_from": norm(st.get("makerSrc")), "dst_chain": dc.get(str(take.get("chainId"))), "dst_tx": None,
            "to": norm(st.get("receiverDst")), "token": norm(take.get("tokenAddress")), "amount_raw": str(take.get("amount") or ""),
            "status": o.get("status")}


def parse_relay_req(r, seed):
    ec = seed.get("evm_chain_ids") or {}
    d = r.get("data") or {}
    ins, outs = d.get("inTxs") or [], d.get("outTxs") or []
    md = d.get("metadata") or {}
    co = (md.get("currencyOut") or {})
    return {"id": r.get("id"), "proto": "relay", "status": r.get("status"),
            "src_chain": ec.get(str((ins[0] if ins else {}).get("chainId"))), "src_tx": norm((ins[0] if ins else {}).get("hash")),
            "src_from": norm(md.get("sender") or r.get("user")),
            "dst_chain": ec.get(str((outs[0] if outs else {}).get("chainId"))), "dst_tx": norm((outs[0] if outs else {}).get("hash")),
            "to": norm(md.get("recipient") or r.get("recipient")), "token": norm((co.get("currency") or {}).get("address")),
            "amount_raw": str(co.get("amount") or ""), "usd": co.get("amountUsd")}


def parse_ccip_msg(d, seed):
    if not isinstance(d, dict) or not d.get("messageId"):
        return None
    sel, nets = seed.get("ccip_chain_selectors") or {}, seed.get("ccip_networks") or {}
    try:
        hdr = (json.loads(d.get("infoRaw") or "{}") or {}).get("header") or {}
    except (TypeError, ValueError, AttributeError):
        hdr = {}
    sc = sel.get(str(hdr.get("sourceChainSelector") or "")) or nets.get(str(d.get("sourceNetworkName") or ""))
    dc = sel.get(str(hdr.get("destChainSelector") or "")) or nets.get(str(d.get("destNetworkName") or ""))
    ta = [t for t in d.get("tokenAmounts") or [] if isinstance(t, dict)]
    t0 = ta[0] if ta else {}
    return {"id": d.get("messageId"), "proto": "ccip", "state": d.get("state"),
            "src_chain": sc, "src_tx": norm(d.get("sendTransactionHash")) or None, "src_from": norm(d.get("sender")) or None,
            "src_ts": d.get("sendTimestamp"),
            "dst_chain": dc, "dst_tx": norm(d.get("receiptTransactionHash")) or None, "to": norm(d.get("receiver")),
            "token_chain": dc, "token": norm(t0.get("destTokenAddress")) or None, "amount_raw": str(t0.get("amount") or ""),
            "src_pools": [norm(t.get("sourcePoolAddress")) for t in ta if t.get("sourcePoolAddress")]}


def pool(lots, need):
    tq = sum((D(x["qty"]) for x in lots), Decimal(0))
    kq = sum((D(x["known"]) for x in lots), Decimal(0))
    kc = sum((D(x["cost"]) for x in lots), Decimal(0))
    need = D(need)
    if need <= 0 or kq <= 0:
        return Decimal(0), Decimal(0)
    frac = kq / max(tq, need)
    cov = need * frac
    return kc / kq * cov, cov


def _scale_lot(x, q_new, **extra):
    q = D(x["qty"])
    f = q_new / q if q > 0 else Decimal(0)
    return dict(x, qty=str(q_new), known=str(D(x["known"]) * f), cost=str(D(x["cost"]) * f), **extra)


def fifo_take(lots, prior, need):
    prior, need = D(prior), D(need)
    out = []
    for x in lots:
        q = D(x["qty"])
        eat = min(q, max(prior, Decimal(0)))
        prior -= eat
        rest = q - eat
        if rest <= 0:
            continue
        take = min(rest, need)
        if take <= 0:
            break
        need -= take
        extra = {"netted": str(eat)} if eat > 0 else {}
        out.append(x if (take == q and not extra) else _scale_lot(x, take, **extra))
    return out


def fits(sent, got, sym_family, rel, stables):
    sent, got = D(sent), D(got)
    if sent <= 0 or got <= 0:
        return False
    lo = sent * (Decimal(1) - rel) - (ABS_STABLE if sym_family in stables else Decimal(0))
    return lo <= got <= sent * (Decimal(1) + Decimal("1e-9"))


def match_pairs(sends, arrivals, links=None, bridge_arr=frozenset(), family=lambda s: s, stables=frozenset(), skip=frozenset()):
    links = links or {}
    by_tx = {}
    for a in arrivals:
        by_tx.setdefault((a["chain"], norm(a["tx"])), []).append(a)
    out, used = {}, set()
    fam_by_tx = {}
    for s in sends:
        if s["pid"] not in skip:
            fam_by_tx.setdefault((s["chain"], norm(s["txn"])), set()).add(family(s["sym"]))
    link_by_src = {}
    for (ac, at), (sc, st) in links.items():
        link_by_src.setdefault((sc, norm(st)), (ac, at, sc, st))
    for s in sends:
        if s["pid"] in skip:
            continue
        hit9 = link_by_src.get((s["chain"], norm(s["txn"])))
        if hit9 is None:
            continue
        ac, at, sc, st = hit9
        cand = [a for a in by_tx.get((ac, norm(at)), []) if a["key"] not in used]
        same = [a for a in cand if family(a["sym"]) == family(s["sym"])]
        if same:
            cand = same
        else:
            sib9 = fam_by_tx.get((sc, norm(st)), set()) - {family(s["sym"])}
            cand = [a for a in cand if family(a["sym"]) not in sib9][:1]
        if cand:
            out[s["pid"]] = (cand[0], "id")
            used.add(cand[0]["key"])
    cs, ca = {}, {}
    arr2 = [a for a in arrivals
            if a["key"] not in used and a.get("ok", True) and (a["chain"], norm(a["tx"])) in bridge_arr]
    for s in sends:
        if s["pid"] in skip or s["pid"] in out or not s.get("ok", True):
            continue
        for a in arr2:
            if a["chain"] == s["chain"]:
                continue
            if family(a["sym"]) != family(s["sym"]):
                continue
            dt = a["ts"] - s["ts"]
            if 0 <= dt <= WINDOW_BRIDGE and fits(s["qty"], a["qty"], family(s["sym"]), REL_SOLVER, stables):
                cs.setdefault(s["pid"], []).append(a)
                ca.setdefault(a["key"], []).append(s["pid"])
    for pid, v in cs.items():
        if len(v) == 1 and len(ca[v[0]["key"]]) == 1:
            out[pid] = (v[0], "window")
    return out


def arr_key(chain, txh, wallet, token):
    return f"{chain}|{norm(txh)}|{norm(wallet)}|{norm(token)}"


def load_cache(state_dir):
    p = os.path.join(state_dir, CACHE_NAME)
    try:
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, json.JSONDecodeError):
        c = {}
    if not isinstance(c, dict) or c.get("v") != CACHE_V:
        c = {"v": CACHE_V}
    for k in ("arr", "snd", "stx", "etx", "ws", "gate", "sigs", "inflows", "outflows", "blk", "dec", "clus"):
        c.setdefault(k, {})
    _rev_hopfifo(c)
    _rev_hopscan(c)
    _rev_hopx(c)
    _rev_hopopen(c)
    return c


def _hop_derived(e) -> bool:
    if not isinstance(e, dict) or e.get("status") != "ok":
        return False
    if e.get("hop"):
        return True
    return any(isinstance(lt, dict) and (lt.get("kind") == "hop" or (lt.get("kind") == "bridge" and lt.get("srcLots")))
               for lt in e.get("lots") or [])


def _rev_hopfifo(c):
    rev = c.setdefault("rev", {})
    if not isinstance(rev, dict):
        rev = c["rev"] = {}
    if REV_HOPFIFO in rev:
        return 0
    drop = [k for k, e in (c.get("arr") or {}).items() if _hop_derived(e)]
    for k in drop:
        c["arr"].pop(k, None)
    rev[REV_HOPFIFO] = {"t": int(time.time()), "dropped": len(drop)}
    return len(drop)


def _none_maybe_capped(c, k, e) -> bool:
    if not isinstance(e, dict) or e.get("status") != "none" or not e.get("hop"):
        return False
    parts = k.split("|")
    if len(parts) < 4:
        return False
    ch, tx, _w, tok = parts[:4]
    if ch == "sol":
        return any(sk.endswith("|" + tx) and isinstance(v, list) and len(v) >= 300 for sk, v in (c.get("sigs") or {}).items())
    blk = ((c.get("etx") or {}).get(f"{ch}|{norm(tx)}") or {}).get("block")
    m = (c.get("inflows") or {}).get(f"{ch}|{norm(tok)}|{norm(e['hop'])}|{blk}")
    if not isinstance(m, list):
        return False
    return sum((D(x.get("qty")) for x in m if isinstance(x, dict)), Decimal(0)) < D(e.get("qty")) * Decimal("0.999")


def _rev_hopscan(c):
    rev = c.setdefault("rev", {})
    if not isinstance(rev, dict):
        rev = c["rev"] = {}
    if REV_HOPSCAN in rev:
        return 0
    drop = [k for k, e in (c.get("arr") or {}).items() if _hop_derived(e) or _none_maybe_capped(c, k, e)
            or (isinstance(e, dict) and e.get("status") == "gate" and "cl" in (e.get("gate") or {}))]
    for k in drop:
        if c["arr"][k].get("status") == "ok":
            c["arr"][k]["stale"] = REV_HOPSCAN
        else:
            c["arr"].pop(k, None)
    clus = [k for k, g in (c.get("clus") or {}).items() if not (isinstance(g, dict) and g.get("v") == 2)]
    for k in clus:
        c["clus"].pop(k, None)
    outs = [k for k, v in (c.get("outflows") or {}).items() if isinstance(v, list) and not k.startswith("bsc|")]
    for k in outs:
        c["outflows"].pop(k, None)
    rev[REV_HOPSCAN] = {"t": int(time.time()), "dropped": len(drop), "keys": drop[:200], "clus": len(clus), "outflows": len(outs)}
    return len(drop)


def _rev_hopx(c):
    rev = c.setdefault("rev", {})
    if not isinstance(rev, dict):
        rev = c["rev"] = {}
    if REV_HOPX in rev:
        return 0
    mark = [k for k, e in (c.get("arr") or {}).items() if _hop_derived(e) and not e.get("stale")]
    for k in mark:
        c["arr"][k]["stale"] = REV_HOPX
    rev[REV_HOPX] = {"t": int(time.time()), "marked": len(mark), "keys": mark[:200]}
    return len(mark)


def _hop_evm(k, e) -> bool:
    if not _hop_derived(e):
        return False
    if (k.split("|")[0] if "|" in k else "") != "sol":
        return True
    return any(isinstance(lt, dict) and (lt.get("chain") or lt.get("src") or "sol") != "sol" for lt in e.get("lots") or [])


def _rev_hopopen(c):
    rev = c.setdefault("rev", {})
    if not isinstance(rev, dict):
        rev = c["rev"] = {}
    if REV_HOPOPEN in rev:
        return 0
    mark = [k for k, e in (c.get("arr") or {}).items() if _hop_evm(k, e)]
    for k in mark:
        c["arr"][k]["reverify"] = REV_HOPOPEN
    rev[REV_HOPOPEN] = {"t": int(time.time()), "marked": len(mark), "keys": mark[:200]}
    return len(mark)


def transit_for(rows, cache, off=frozenset(), external=frozenset()):
    ents = {}
    for k, e in (cache.get("arr") or {}).items():
        if not isinstance(e, dict) or e.get("status") != "ok" or D(e.get("cost")) <= 0:
            continue
        if e.get("reverify"):
            continue
        if norm(k.split("|")[1]) in off or any(norm(h) in external for h in e.get("hops") or ()):
            continue
        ents[k] = e
    out = {}
    if not ents:
        return out
    for r in rows:
        if r["leg_kind"] != "acq" or r["cost_usd"] is not None or r["event"] not in ("TRANSFER_IN", "PROGRAM_IN"):
            continue
        loc = r["location"] or ""
        if not loc.startswith("wallet:"):
            continue
        e = ents.get(arr_key(r["source_ns"], r["source_id"], loc.split(":", 2)[2], r["address"]))
        if e:
            out[r["posting_id"]] = {"qty": D(e["qty"]), "cost": D(e["cost"]), "cov": D(e["cov"]), "label": e.get("label") or "",
                                    "via": e.get("via") or "", "proto": e.get("proto"),
                                    "lots": e.get("lots") if isinstance(e.get("lots"), list) else None}
    return out


def links_for(cache):
    out = {}
    for k, e in (cache.get("arr") or {}).items():
        if isinstance(e, dict) and e.get("status") == "link" and e.get("src_chain") and e.get("src_tx"):
            ch, tx = k.split("|")[:2]
            out[(ch, tx)] = (e["src_chain"], e["src_tx"])
    return out


def bridge_arrivals(cache):
    return {tuple(k.split("|")[:2]) for k, e in (cache.get("arr") or {}).items()
            if isinstance(e, dict) and (e.get("proto") or e.get("solver"))}


def candidates(rows, cache, explained=frozenset(), stable_gids=frozenset(), now=None, stable_min=Decimal("500")):
    now = now or time.time()
    used = set()
    for r in rows:
        if (r["event"] == "TRANSFER_OUT_EX" and r["leg_kind"] == "move_out") or (r["event"] == "SWAP" and r["leg_kind"] == "disp"):
            used.add(r["group_id"] or -r["asset_id"])
    out = []
    for r in rows:
        if r["leg_kind"] != "acq" or r["cost_usd"] is not None or r["event"] not in ("TRANSFER_IN", "PROGRAM_IN"):
            continue
        loc = r["location"] or ""
        if not loc.startswith("wallet:"):
            continue
        txh = r["source_id"] or ""
        if txh in explained or txh.lower() in explained:
            continue
        if r["address"] in (None, "", "native"):
            continue
        gid = r["group_id"] or -r["asset_id"]
        dec = r["decimals"] if r["decimals"] is not None else 18
        q = Decimal(int(r["qty_base"])) / (Decimal(10) ** int(dec))
        if gid in stable_gids:
            if q < stable_min:
                continue
        elif gid not in used:
            continue
        wallet = loc.split(":", 2)[2]
        k = arr_key(r["source_ns"], txh, wallet, r["address"])
        e = (cache.get("arr") or {}).get(k)
        if e and (e.get("stale") or e.get("reverify")) and e.get("rt"):
            if now - float(e.get("rt") or 0) < (BUDGET_RETRY_SEC if e.get("rst") in ("budget", "paused", "wait") else RETRY_SEC):
                continue
        if e and not (e.get("stale") or e.get("reverify")):
            st = e.get("status")
            age = now - float(e.get("t") or 0)
            if st in ("paused", "wait"):
                if age < WAIT_SEC:
                    continue
            elif st == "budget":
                if age < BUDGET_RETRY_SEC:
                    continue
            elif st in ("ok", "link", "none") or (st == "gate" and age < 7 * 86400) or age < RETRY_SEC:
                continue
        out.append({"key": k, "chain": r["source_ns"], "tx": txh, "wallet": wallet, "token": r["address"] or "",
                    "sym": r["symbol"], "qty": str(q), "ts": int(r["event_ts"]), "stable": gid in stable_gids})
    out.sort(key=lambda c: -c["ts"])
    return out


def _rv(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


class _ArrivalIndex:

    def __init__(self, rows):
        self.rows, self.tx, self.amt = rows, None, None

    def _build(self):
        self.tx, self.amt = set(), set()
        for r in self.rows:
            loc = _rv(r, "location") or ""
            if _rv(r, "leg_kind") not in ("acq", "move_in") or not loc.startswith("wallet:"):
                continue
            self.tx.add((_rv(r, "source_ns"), norm(_rv(r, "source_id"))))
            if _rv(r, "qty_base") is not None:
                self.amt.add((loc, norm(_rv(r, "address")), str(_rv(r, "qty_base"))))

    def any_of(self, ops):
        if not ops:
            return False
        if self.tx is None:
            self._build()
        for op in ops:
            if op.get("dst_tx") and (op.get("dst_chain"), norm(op["dst_tx"])) in self.tx:
                return True
            if not op.get("dst_tx") and op.get("amount_raw") and op.get("to") and op.get("token") and \
                    (f"wallet:{op.get('dst_chain')}:{op['to']}", norm(op["token"]), str(op["amount_raw"])) in self.amt:
                return True
        return False


def _memo_ops(cache, txh):
    t = norm(txh)
    ws = cache.get("ws") or {}
    out = []
    for k in (t, "relay:" + t, "dln:" + t, "ccip:" + t):
        for op in ws.get(k) or []:
            if isinstance(op, dict) and norm(op.get("src_tx")) == t and op.get("dst_chain"):
                out.append(op)
    return out


def send_candidates(rows, cache, seed, now=None):
    now = now or time.time()
    known = set(seed.get("evm_contracts") or {}) | set(seed.get("solvers") or {}) | set(seed.get("sol_programs") or {})
    out, seen = [], set()
    arrived = _ArrivalIndex(rows)
    for r in rows:
        loc = r["location"] or ""
        dest = loc.split(":", 2)[2] if loc.startswith("out:") and loc.count(":") >= 2 else None
        if not (r["leg_kind"] == "move_in" and dest and norm(dest) in known):
            continue
        k = f"S|{r['source_ns']}|{norm(r['source_id'])}"
        if k in seen:
            continue
        seen.add(k)
        e = (cache.get("snd") or {}).get(k)
        if e and e.get("status") in ("wait", "paused"):
            if now - float(e.get("t") or 0) < WAIT_SEC:
                continue
        elif e and e.get("status") == "none" and e.get("w0"):
            if not arrived.any_of(_memo_ops(cache, r["source_id"])):
                continue
        elif e and e.get("status") == "budget":
            if now - float(e.get("t") or 0) < BUDGET_RETRY_SEC:
                continue
        elif e and (e.get("status") in ("link", "none") or now - float(e.get("t") or 0) < RETRY_SEC):
            continue
        proto = ((seed.get("evm_contracts") or {}).get(norm(dest)) or (seed.get("solvers") or {}).get(norm(dest))
                 or (seed.get("sol_programs") or {}).get(dest or "") or {}).get("proto")
        out.append({"kind": "send", "key": k, "chain": r["source_ns"], "tx": r["source_id"], "ts": int(r["event_ts"]), "proto": proto})
    out.sort(key=lambda c: -c["ts"])
    return out


def _fail_class(e, block=None, head=None) -> str:
    import bf_engine
    return bf_engine.rpc_fail_class(e, block=block, head=head)


def _definitive(e) -> bool:
    return isinstance(e, urllib.error.HTTPError) and 400 <= int(getattr(e, "code", 0) or 0) < 500 \
        and int(e.code) not in (408, 425, 429)


class ScanCap(RuntimeError):
    pass


class ApiDown(RuntimeError):
    pass


class Budget(Exception):
    pass


class Paused(Budget):
    pass


class Tracer:

    def __init__(self, cfg, cache, ledger, seed, px=None, budget=300, sleep=0.35, log=None, anchors=None, skip_gids=None, cex=None):
        self.cfg, self.c, self.db, self.seed, self.px = cfg, cache, ledger, seed, px
        self.budget, self.sleep, self.log = budget, sleep, log or (lambda *a: None)
        self.calls = 0
        self.skip_gids = frozenset(skip_gids or ())
        self.mine = {norm(w.get("address")) for w in _cm9.history_wallets(cfg) if w.get("address")}
        self.anchors = {norm(a): v for a, v in (anchors or {}).items() if a and norm(a) not in self.mine}
        self.cex = {norm(a) for a in (cex or ()) if a} - self.mine
        sol = cfg.get("sol") or {}
        self.sol_urls = [u for u in ([sol.get("rpc_fallback")] + list(sol.get("rpc_fallbacks") or [])) if u and u.startswith("http")]
        if "https://api.mainnet-beta.solana.com" not in self.sol_urls:
            self.sol_urls.append("https://api.mainnet-beta.solana.com")
        self.sol_urls.sort(key=lambda u: 0 if "mainnet-beta" in u else 1)

    def _post(self, url, method, params, timeout=30):
        if self.calls >= self.budget:
            raise Budget()
        self.calls += 1
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "tj-bot/0.1 (personal trade journal)"})
        netpace.wait(url)
        try:
            import bf_engine as _bfe9
            if "_" in str(method):
                try:
                    d = _bfe9.rpc_post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout,
                                       ua="tj-bot/0.1 (personal trade journal)")
                except (_bfe9.NetError, getattr(_bfe9, "RpcTransportError", OSError)) as e8:
                    if getattr(e8, "code", None) is not None or getattr(e8, "kind", None) == "http429":
                        netpace.note_error(url, e8)
                    raise
                if not isinstance(d, dict):
                    raise RuntimeError(f"rpc {method}: 응답 형식 오류 ({type(d).__name__})")
                if "error" in d:
                    ce9 = _bfe9.classify_rpc_error(d["error"])
                    raise _bfe9.NetError(str(d["error"])[:200], ce9.kind, code=ce9.code)
                return d.get("result")
            with _bfe9.sol_open(req, timeout, method, sol=("_" not in str(method))) as r:
                d = json.loads(_cm9.read_capped(r).decode())
        except urllib.error.HTTPError as e:
            netpace.note_error(url, e)
            raise
        finally:
            time.sleep(self.sleep)
        if "error" in d:
            raise RuntimeError(str(d["error"])[:200])
        return d.get("result")

    def _get(self, url, timeout=30):
        if self.calls >= self.budget:
            raise Budget()
        self.calls += 1
        req = urllib.request.Request(url, headers={"User-Agent": "tj-bot/0.1 (personal trade journal)", "Accept": "application/json"})
        try:
            netpace.wait(url)
        except netpace.Cooldown as e:
            raise Paused(str(e))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(_cm9.read_capped(r).decode())
        except urllib.error.HTTPError as e:
            if netpace.note_error(url, e):
                raise Paused(f"{netpace.host_of(url)} 429")
            raise
        finally:
            time.sleep(self.sleep)

    def _sol(self, method, params):
        err = None
        for u in self.sol_urls:
            try:
                return self._post(u, method, params)
            except Budget:
                raise
            except Exception as e:
                err = e
        raise RuntimeError(f"sol {method}: {err}")

    def _evm_urls(self, chain, logs=False):
        if chain == "bsc":
            b = self.cfg.get("bsc") or {}
            if logs:
                return ["https://bsc.rpc.sentio.xyz"] + [u for u in b.get("logs_rpcs") or [] if "nodereal" not in u]
            return list(b.get("detail_rpcs") or []) + [u for u in b.get("logs_rpcs") or [] if "nodereal" not in u]
        c = (self.cfg.get("chains") or {}).get(chain) or {}
        return list((c.get("rpc_logs") if logs else None) or c.get("rpcs") or [])

    def _evm(self, chain, method, params, logs=False):
        err = None
        errs = []
        for u in self._evm_urls(chain, logs):
            try:
                r = self._post(u, method, params)
                if r is None and method != "eth_getLogs":
                    err = "null(가지치기 노드)"
                    errs.append(err)
                    continue
                return r
            except Budget:
                raise
            except Exception as e:
                err = e
                errs.append(e)
        ex = RuntimeError(f"{chain} {method}: {err}")
        ex.errs = errs or ["엔드포인트 없음"]
        raise ex

    def sol_tx(self, sig):
        m = self.c["stx"]
        if not m.get(sig):
            ct = compact_sol_tx(self._sol("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]))
            if ct is None:
                raise RuntimeError("tx 없음")
            m[sig] = ct
        return m[sig]

    def sol_sigs(self, acct, before, pages=SOL_SIG_PAGES):
        k = f"{acct}|{before}"
        if k not in self.c["sigs"]:
            out, cur = [], before
            for _ in range(pages):
                p = {"limit": SOL_SIG_PAGE}
                if cur:
                    p["before"] = cur
                r = self._sol("getSignaturesForAddress", [acct, p]) or []
                out += [{"sig": x["signature"], "err": x.get("err") is not None, "ts": x.get("blockTime")} for x in r]
                if len(r) < SOL_SIG_PAGE:
                    break
                cur = r[-1]["signature"]
            self.c["sigs"][k] = out
        return self.c["sigs"][k]

    def ws_op(self, txh):
        k = norm(txh)
        if k not in self.c["ws"]:
            try:
                d = self._get(f"https://api.wormholescan.io/api/v1/operations?txHash={txh}")
                ops = (d or {}).get("operations") or []
                self.c["ws"][k] = [parse_ws_op(o, self.seed) for o in ops]
            except Budget:
                raise
            except Exception as e:
                self.log(f"wormholescan {short(txh)}: {e}")
                if _definitive(e):
                    self.c["ws"][k] = []
                    return []
                return None
        return self.c["ws"][k]

    def debridge(self, txh):
        k = "dln:" + norm(txh)
        if k not in self.c["ws"]:
            try:
                ids = (self._get(f"https://dln.debridge.finance/v1.0/dln/tx/{txh}/order-ids") or {}).get("orderIds") or []
                res = []
                for oid in ids:
                    oid = oid.get("stringValue") if isinstance(oid, dict) else oid
                    res.append(parse_dln_order(self._get(f"https://dln.debridge.finance/v1.0/dln/order/{oid}") or {}, txh, self.seed))
                self.c["ws"][k] = res
            except Budget:
                raise
            except Exception as e:
                self.log(f"debridge {short(txh)}: {e}")
                if _definitive(e):
                    self.c["ws"][k] = []
                    return []
                return None
        return self.c["ws"][k]

    def relay(self, txh):
        k = "relay:" + norm(txh)
        if k not in self.c["ws"]:
            try:
                d = self._get(f"https://api.relay.link/requests/v2?hash={txh}") or {}
                self.c["ws"][k] = [parse_relay_req(r, self.seed) for r in (d.get("requests") or [])]
            except Budget:
                raise
            except Exception as e:
                self.log(f"relay {short(txh)}: {e}")
                if _definitive(e):
                    self.c["ws"][k] = []
                    return []
                return None
        return self.c["ws"][k]

    def ccip(self, txh):
        k = "ccip:" + norm(txh)
        if k not in self.c["ws"]:
            try:
                s = self._get(f"https://ccip.chain.link/api/h/atlas/search?msgIdOrTxnHash={txh}") or {}
                ids = []
                for f in ("destTransactionHash", "transactionHash", "messageId"):
                    for it in s.get(f) or []:
                        mid = it.get("messageId") if isinstance(it, dict) else it
                        if mid and mid not in ids:
                            ids.append(mid)
                self.c["ws"][k] = [parse_ccip_msg(self._get(f"https://ccip.chain.link/api/h/atlas/message/{m}") or {}, self.seed)
                                   for m in ids]
            except Budget:
                raise
            except Exception as e:
                self.log(f"ccip {short(txh)}: {e}")
                if _definitive(e):
                    self.c["ws"][k] = []
                    return []
                return None
        return self.c["ws"][k]

    def resolve(self, chain, txh, proto=None):
        order = {"relay": ("relay",), "debridge": ("dln",), "ccip": ("ccip",), "across": (), "allbridge": (),
                 "layerzero": ()}.get(proto or "", ("ws", "relay", "dln", "ccip"))
        down = []
        for src in order:
            ops = self.ws_op(txh) if src == "ws" else (self.relay(txh) if src == "relay" else
                                                         (self.ccip(txh) if src == "ccip" else self.debridge(txh)))
            if ops is None:
                down.append(src)
                continue
            ops = [o for o in ops if o]
            if ops:
                return ops
        if down:
            raise ApiDown(f"브릿지 API 일시 실패: {','.join(down)} ({short(txh)})")
        return []

    def _head(self, chain):
        return int(self._evm(chain, "eth_blockNumber", []) or "0x0", 16)

    def receipt(self, chain, h):
        k = f"{chain}|{norm(h)}"
        if not self.c["etx"].get(k):
            r = self._evm(chain, "eth_getTransactionReceipt", [h])
            t = self._evm(chain, "eth_getTransactionByHash", [h])
            cr = compact_receipt(r, t)
            if cr is None:
                raise RuntimeError("영수증 없음")
            self.c["etx"][k] = cr
        return self.c["etx"][k]

    def block_ts(self, chain, n):
        k = f"{chain}|{n}"
        if not self.c["blk"].get(k):
            b = self._evm(chain, "eth_getBlockByNumber", [hex(n), False]) or {}
            ts = int(b.get("timestamp") or "0x0", 16)
            if not ts:
                return 0
            self.c["blk"][k] = ts
        return self.c["blk"][k]

    def decimals(self, chain, token):
        k = f"{chain}|{norm(token)}"
        if k not in self.c["dec"]:
            r = self._evm(chain, "eth_call", [{"to": token, "data": "0x313ce567"}, "latest"])
            self.c["dec"][k] = int(r, 16) if r and r != "0x" else 18
        return self.c["dec"][k]

    def native_px(self, chain, ts):
        if not self.px or not ts:
            return None
        sym = NATIVE.get(chain)
        if sym in ("XDAI", "USDC"):
            return 1.0
        try:
            return self.px.candle_usd("BNB" if sym == "BNB" else sym, int(ts) * 1000)
        except Exception:
            return None

    def _span(self, chain):
        c = (self.cfg.get("chains") or {}).get(chain) or {}
        return 10000 if chain == "bsc" else int(((c.get("rpc_log_span_caps") or {}) and min((c.get("rpc_log_span_caps") or {}).values())) or 2000)

    def _bs(self, chain):
        bs = str((((self.cfg.get("chains") or {}).get(chain) or {}).get("blockscout")) or "").rstrip("/")
        return bs if bs and chain != "bsc" else ""

    def _scan_state(self, kind, chain, token, holder, before_block):
        if kind == "to":
            m, k = self.c["inflows"], f"{chain}|{norm(token)}|{norm(holder)}|{before_block}"
        else:
            m, k = self.c.setdefault("outflows", {}), f"{chain}|{norm(token)}|{norm(holder)}|<{before_block}"
        st = m.get(k)
        if isinstance(st, dict) and st.get("v") == 2 and isinstance(st.get("items"), list):
            return st, k, None
        return None, k, (st if isinstance(st, list) else None)

    def _scan_new(self, kind, k, before_block):
        st = {"v": 2, "items": [], "cur": None, "done": False, "full": int(before_block), "n": 0}
        (self.c["inflows"] if kind == "to" else self.c["outflows"])[k] = st
        return st

    def _scan_page(self, kind, chain, token, holder, before_block, st):
        if st["done"]:
            return False
        dec = self.decimals(chain, token)
        bs = self._bs(chain)
        if bs:
            if st["n"] >= MAX_PAGES:
                raise ScanCap(f"{chain} {short(holder)} {'유입' if kind == 'to' else '유출'} 조회 상한 {MAX_PAGES}쪽")
            q = f"{bs}/api/v2/addresses/{holder}/token-transfers?type=ERC-20&filter={kind}&token={token}"
            url = q + ("&" + "&".join(f"{a}={b}" for a, b in st["cur"].items()) if isinstance(st.get("cur"), dict) else "")
            d = self._get(url) or {}
            low = None
            for it in d.get("items") or []:
                bn = int(it.get("block_number") or 0)
                low = bn if low is None else min(low, bn)
                if bn >= before_block:
                    continue
                v = D((it.get("total") or {}).get("value")) / (Decimal(10) ** dec)
                row = {"block": bn, "tx": norm(it.get("transaction_hash") or it.get("tx_hash")), "qty": str(v)}
                if kind == "to":
                    row["from"] = norm((it.get("from") or {}).get("hash"))
                else:
                    row["to"] = norm((it.get("to") or {}).get("hash"))
                st["items"].append(row)
            np_ = d.get("next_page_params")
            st["n"] += 1
            st["cur"] = np_ if isinstance(np_, dict) and np_ else None
            if not st["cur"]:
                st["done"], st["full"] = True, 0
            elif low is not None:
                st["full"] = min(st["full"], low + 1)
            return True
        if st["n"] >= MAX_WINDOWS:
            raise ScanCap(f"{chain} {short(holder)} {'유입' if kind == 'to' else '유출'} 조회 상한 {MAX_WINDOWS}창")
        span = self._span(chain)
        hi = int(st["cur"]) if st.get("cur") is not None else int(before_block) - 1
        if hi < 0:
            st["done"], st["full"] = True, 0
            return False
        lo = max(0, hi - span + 1)
        topic = "0x" + "0" * 24 + norm(holder)[2:]
        tp = [TR, None, topic] if kind == "to" else [TR, topic, None]
        lg = self._evm(chain, "eth_getLogs", [{"address": token, "fromBlock": hex(lo), "toBlock": hex(hi), "topics": tp}], logs=True) or []
        for x in reversed(lg):
            row = {"block": int(x["blockNumber"], 16), "tx": norm(x["transactionHash"]), "qty": str(D(int(x["data"], 16)) / (Decimal(10) ** dec))}
            if kind == "to":
                row["from"] = "0x" + x["topics"][1][26:]
            else:
                row["to"] = "0x" + x["topics"][2][26:]
            st["items"].append(row)
        st["n"] += 1
        st["cur"], st["full"] = lo - 1, lo
        if lo == 0:
            st["done"] = True
        return True

    def evm_inflows(self, chain, token, holder, before_block, need):
        st, k, old = self._scan_state("to", chain, token, holder, before_block)
        need = D(need)
        if st is None:
            if old is not None and sum((D(x["qty"]) for x in old), Decimal(0)) >= need:
                return old
            st = self._scan_new("to", k, before_block)
        while not st["done"] and sum((D(x["qty"]) for x in st["items"]), Decimal(0)) < need:
            self._scan_page("to", chain, token, holder, before_block, st)
        return st["items"]

    def evm_inflows_more(self, chain, token, holder, before_block):
        st, k, old = self._scan_state("to", chain, token, holder, before_block)
        if st is None:
            st = self._scan_new("to", k, before_block)
            while not st["done"] and len(st["items"]) <= len(old or []):
                self._scan_page("to", chain, token, holder, before_block, st)
            return True
        return self._scan_page("to", chain, token, holder, before_block, st)

    def evm_inflows_done(self, chain, token, holder, before_block):
        st, _k, _old = self._scan_state("to", chain, token, holder, before_block)
        return bool(st and st["done"])

    def _legacy_out_ok(self, chain, lst, lo_block, before_block):
        if not isinstance(lst, list):
            return False
        if self._bs(chain):
            return len(lst) < 250
        return before_block - lo_block <= 36 * self._span(chain)

    def evm_outflows(self, chain, token, holder, lo_block, before_block):
        lo_block, before_block = int(lo_block), int(before_block)
        old = (self.c.get("outflows") or {}).get(f"{chain}|{norm(token)}|{norm(holder)}|{lo_block}|{before_block}")
        if self._legacy_out_ok(chain, old, lo_block, before_block):
            return old
        st, k, _o = self._scan_state("from", chain, token, holder, before_block)
        if st is None:
            st = self._scan_new("from", k, before_block)
        while not st["done"] and st["full"] > lo_block:
            self._scan_page("from", chain, token, holder, before_block, st)
        return [o for o in st["items"] if lo_block <= int(o["block"]) < before_block]

    def _same_block_prior(self, chain, token, H, block, cur):
        if not cur or not cur[0] or not str(H).startswith("0x"):
            return Decimal(0)
        ctx, cto = norm(cur[0]), (norm(cur[1]) if cur[1] else None)
        tokn, Hn = norm(token), norm(H)
        out = Decimal(0)
        if cto:
            cr = (self.c.get("etx") or {}).get(f"{chain}|{ctx}")
            if cr:
                dec = None
                for lg in cr.get("logs") or []:
                    t9 = lg.get("t") or []
                    if len(t9) != 3 or t9[0] != TR or lg.get("a") != tokn or "0x" + t9[1][26:] != Hn:
                        continue
                    if "0x" + t9[2][26:] == cto:
                        break
                    if dec is None:
                        dec = self.decimals(chain, token)
                    try:
                        out += D(int(lg.get("d") or "0x0", 16)) / (Decimal(10) ** dec)
                    except ValueError:
                        continue
        sib = False
        if self.db is not None:
            try:
                for (h9, snap9) in self.db.execute("SELECT txhash, snapshot FROM raw_txs WHERE chain=? AND block=?", (chain, int(block))):
                    if norm(h9) != ctx and Hn[2:] in str(snap9 or "").lower():
                        sib = True
                        break
            except Exception:
                sib = False
        if not sib:
            return out
        m = self.c.setdefault("sblk", {})
        k = f"{chain}|{tokn}|{Hn}|{int(block)}"
        rows = m.get(k)
        if not isinstance(rows, list):
            topic = "0x" + "0" * 24 + Hn[2:]
            lg = self._evm(chain, "eth_getLogs", [{"address": token, "fromBlock": hex(int(block)), "toBlock": hex(int(block)),
                                                   "topics": [TR, topic, None]}], logs=True) or []
            dec = self.decimals(chain, token)
            rows = []
            for x in lg:
                try:
                    rows.append({"ti": int(x.get("transactionIndex") or "0x0", 16), "li": int(x.get("logIndex") or "0x0", 16),
                                 "tx": norm(x.get("transactionHash")), "to": "0x" + x["topics"][2][26:],
                                 "qty": str(D(int(x.get("data") or "0x0", 16)) / (Decimal(10) ** dec))})
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
            rows.sort(key=lambda r: (r["ti"], r["li"]))
            m[k] = rows
        ti9 = next((r["ti"] for r in rows if r["tx"] == ctx), None)
        if ti9 is None:
            return out
        return out + sum((D(r["qty"]) for r in rows if r["ti"] < ti9), Decimal(0))

    def _net_prior_out(self, chain, H, token, before_block, need, lots, complete=False, cur=None):
        need = D(need)
        tq = sum((D(x["qty"]) for x in lots), Decimal(0))
        blocks = [x.get("block") for x in lots if x.get("block")]
        if not lots or need <= 0 or len(blocks) != len(lots):
            return lots if (complete or tq >= need * Decimal("0.999") or need <= 0) else None
        lo_b = min(blocks)
        prior = sum((D(o["qty"]) for o in self.evm_outflows(chain, token, H, lo_b, before_block)
                     if lo_b <= int(o["block"]) < before_block), Decimal(0))
        prior = max(prior, Decimal(0))
        same = self._same_block_prior(chain, token, H, before_block, cur)
        if not complete:
            opening = self._hop_opening(chain, token, H, before_block, tq, prior)
            if opening is not None and opening > need * Decimal("0.001"):
                if opening > (prior + same) * Decimal("1.001"):
                    return None
                prior = max(prior + same - opening, Decimal(0))
                same = Decimal(0)
        prior += same
        if tq - prior < need * Decimal("0.999") and not complete:
            return None
        order = sorted(range(len(lots)), key=lambda i: (lots[i]["block"], -i))
        return fifo_take([lots[i] for i in order], prior, need)

    def _hop_opening(self, chain, token, H, before_block, tq, prior):
        bk = f"{chain}|{norm(token)}|{norm(H)}|{int(before_block)}"
        memo = self.c.setdefault("hop_bal", {})
        if bk not in memo:
            try:
                raw = self._evm(chain, "eth_call", [{"to": token, "data": "0x70a08231" + norm(H)[2:].zfill(64)},
                                                    hex(int(before_block) - 1)])
            except Budget:
                raise
            except Exception as e9:
                if _fail_class(e9, block=int(before_block) - 1, head=lambda: self._head(chain)) == "transient":
                    raise Paused(f"창 앞 잔고 조회 일시 실패 — 다음에 다시({chain} {short(H)}): {str(e9)[:120]}") from e9
                return None
            if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) != 66:
                return None
            memo[bk] = str(int(raw, 16))
        bal = D(memo[bk]) / (Decimal(10) ** int(self.decimals(chain, token)))
        opening = bal - tq + prior
        return opening if opening >= 0 else None

    def gate(self, addr):
        a = norm(addr)
        g = self.c["gate"].get(a)
        if g and g.get("v") == 2 and time.time() - float(g.get("t") or 0) < 7 * 86400:
            return g
        to_hop = Decimal(0)
        stab_g = ('USDT', 'USDC', 'DAI', 'USDE', 'USDG', 'FDUSD', 'BUSD', 'USD1', 'PYUSD')
        for v, gid9, trade9, held9 in self.db.execute(
                "SELECT p.cost_usd, a.group_id,"
                " (a.kind IN ('native', 'exchange_currency') OR g.name IN (" + ",".join("?" * len(stab_g)) + ")"
                "  OR EXISTS (SELECT 1 FROM postings q WHERE q.asset_id = p.asset_id AND q.cost_usd IS NOT NULL"
                "   AND ((q.leg_kind IN ('acq', 'disp') AND q.event IN ('SWAP', 'CONVERT', 'EX_BUY', 'EX_SELL', 'EXF_BUY', 'EXF_SELL'))"
                "    OR q.event LIKE 'LP_%'))),"
                " EXISTS (SELECT 1 FROM postings h WHERE h.asset_id = p.asset_id AND h.location LIKE 'wallet:%'"
                "  AND h.leg_kind IN ('acq', 'opening', 'move_in') AND CAST(h.qty_base AS REAL) > 0)"
                " FROM postings p JOIN assets a ON a.asset_id = p.asset_id LEFT JOIN asset_groups g ON g.group_id = a.group_id"
                " WHERE p.leg_kind='move_in' AND p.location LIKE ?", (*stab_g, f"out:%:{a}")):
            if v is None or not (trade9 or (held9 and gid9 not in self.skip_gids)):
                continue
            to_hop += D(v)
        from_hop = Decimal(0)
        pat = f"%{a}%"
        stab = {r[0] for r in self.db.execute("SELECT group_id FROM asset_groups WHERE name IN ('USDT','USDC','DAI','USDE','USDG','FDUSD','BUSD','USD1','PYUSD')")}
        q = ("SELECT r.chain, r.txhash, r.snapshot FROM raw_txs r WHERE " +
             ("lower(r.snapshot) LIKE ?" if a.startswith("0x") else "r.snapshot LIKE ?"))
        for ch, h, snap in self.db.execute(q, (pat,)):
            try:
                s = json.loads(snap)
            except (TypeError, ValueError):
                continue
            if ch == "sol":
                if s.get("fee_payer") != a:
                    continue
            else:
                tx = s.get("tx") or {}
                fr = tx.get("from")
                fr = norm(fr.get("hash") if isinstance(fr, dict) else fr)
                tts = [t for t in s.get("token_transfers") or [] if norm((t.get("from") or {}).get("hash") if isinstance(t.get("from"), dict) else t.get("from")) == a]
                if fr != a and not tts:
                    continue
                if fr != a:
                    continue
            for gid, qb, dec, cu, lk in self.db.execute(
                    "SELECT a.group_id, p.qty_base, a.decimals, p.cost_usd, p.leg_kind FROM postings p JOIN assets a USING(asset_id)"
                    " WHERE p.source_ns=? AND p.source_id=? AND p.location LIKE 'wallet:%' AND p.leg_kind IN ('acq','move_in')", (ch, h)):
                qn = Decimal(int(qb)) / (Decimal(10) ** int(dec if dec is not None else 18))
                if gid in stab and qn > 0:
                    from_hop += qn
                elif cu is not None and qn > 0:
                    from_hop += D(cu)
        g = {"to_hop": str(to_hop), "from_hop": str(from_hop), "t": int(time.time()), "v": 2}
        self.c["gate"][a] = g
        return g

    def cluster(self, chain, addr, enough=None):
        a, k = norm(addr), f"{chain}|{norm(addr)}"
        m = self.c.setdefault("clus", {})
        g = m.get(k)
        fresh = isinstance(g, dict) and time.time() - float(g.get("t") or 0) < 7 * 86400
        if fresh and g.get("v") != 2:
            return g
        ok = (lambda gi, go: enough(gi, go)) if enough else (lambda gi, go: False)
        if fresh and (g.get("done") or g.get("capped") or ok(D(g.get("in")), D(g.get("out")))):
            return g
        if not fresh:
            g = {"v": 2, "in": "0", "out": "0", "via_in": None, "via_out": None, "t": int(time.time()), "vin": {}, "vout": {},
                 "tt": None, "tx": None, "ntt": 0, "ntx": 0, "ttd": False, "txd": False, "done": False, "capped": False}
        m[k] = g
        bs = str(((self.cfg.get("chains") or {}).get(chain) or {}).get("blockscout") or "").rstrip("/")
        if not bs or not a.startswith("0x") or not self.anchors:
            g.update(done=True, ttd=True, txd=True)
            return g
        st = {norm(x) for x in _stable_cas(chain)}

        def add(frm, to, usd):
            if usd <= 0:
                return
            if frm == a and to in self.anchors:
                g["out"] = str(D(g["out"]) + usd)
                g["vout"][to] = str(D(g["vout"].get(to)) + usd)
            elif to == a and frm in self.anchors:
                g["in"] = str(D(g["in"]) + usd)
                g["vin"][frm] = str(D(g["vin"].get(frm)) + usd)

        def fin():
            vin = {x: D(v) for x, v in g["vin"].items()}
            vout = {x: D(v) for x, v in g["vout"].items()}
            g["via_in"] = max(vin, key=vin.get) if vin else None
            g["via_out"] = max(vout, key=vout.get) if vout else None
            g["done"] = bool(g["ttd"] and g["txd"])
            return g
        while not g["ttd"] and not ok(D(g["in"]), D(g["out"])):
            if g["ntt"] >= CLUS_PAGES_TT:
                g["capped"] = True
                break
            d = self._get(g["tt"] or f"{bs}/api/v2/addresses/{a}/token-transfers?type=ERC-20") or {}
            for it in d.get("items") or []:
                tok = norm((it.get("token") or {}).get("address_hash") or (it.get("token") or {}).get("address"))
                if tok not in st:
                    continue
                dec = int((it.get("total") or {}).get("decimals") or (it.get("token") or {}).get("decimals") or 6)
                add(norm((it.get("from") or {}).get("hash")), norm((it.get("to") or {}).get("hash")),
                    D((it.get("total") or {}).get("value")) / (Decimal(10) ** dec))
            np_ = d.get("next_page_params")
            g["ntt"] += 1
            g["tt"] = (f"{bs}/api/v2/addresses/{a}/token-transfers?type=ERC-20&" + "&".join(f"{x}={y}" for x, y in np_.items())) if np_ else None
            g["ttd"] = not np_
        if not self.px:
            g["txd"] = True
        while not g["txd"] and not ok(D(g["in"]), D(g["out"])):
            if g["ntx"] >= CLUS_PAGES_TX:
                g["capped"] = True
                break
            d = self._get(g["tx"] or f"{bs}/api/v2/addresses/{a}/transactions") or {}
            for it in d.get("items") or []:
                v = D(it.get("value")) / Decimal(10 ** 18)
                if v <= 0 or it.get("status") not in (None, "ok"):
                    continue
                ts = it.get("timestamp")
                try:
                    ts = calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")) if ts else None
                except ValueError:
                    ts = None
                px = self.native_px(chain, ts)
                if px:
                    add(norm((it.get("from") or {}).get("hash")), norm((it.get("to") or {}).get("hash")), v * D(px))
            np_ = d.get("next_page_params")
            g["ntx"] += 1
            g["tx"] = (f"{bs}/api/v2/addresses/{a}/transactions?" + "&".join(f"{x}={y}" for x, y in np_.items())) if np_ else None
            g["txd"] = not np_
        return fin()

    def own_ok(self, addr, level, chain=None):
        a = norm(addr)
        if a in self.mine:
            return True
        if a in self.cex:
            return False
        if not self._own_ok_flows(addr, level, chain):
            return False
        if chain and chain != "sol" and a.startswith("0x") and self._busy_or_contract(chain, a):
            return False
        return True

    def _busy_or_contract(self, chain, a):
        m = self.c.setdefault("acct", {})
        k = f"{chain}|{a}"
        e = m.get(k)
        if isinstance(e, dict) and time.time() - float(e.get("t") or 0) < ACCT_TTL:
            return bool(e.get("busy") or e.get("code"))
        try:
            n = int(self._evm(chain, "eth_getTransactionCount", [a, "latest"]) or "0x0", 16)
            code = str(self._evm(chain, "eth_getCode", [a, "latest"]) or "0x").lower()
        except Budget:
            raise
        except Exception as ex:
            self.log(f"acct {chain} {short(a)}: {ex}")
            if _fail_class(ex) == "transient":
                raise Paused(f"계정 조회 일시 실패 — 다음에 다시({chain} {short(a)}): {str(ex)[:120]}") from ex
            return False
        e = {"t": int(time.time()), "n": n, "busy": n >= HOP_MAX_NONCE,
             "code": code not in ("0x", "0x0", "") and not code.startswith("0xef0100")}
        m[k] = e
        return bool(e["busy"] or e["code"])

    def _own_ok_flows(self, addr, level, chain=None):
        if norm(addr) in self.mine:
            return True
        g = self.gate(addr)
        th, fh = D(g["to_hop"]), D(g["from_hop"])
        if (th >= GATE_USD and fh >= GATE_USD) if level == "direct" else (th >= GATE_USD or fh >= GATE_USD):
            return True
        if not self.anchors:
            return False
        a = norm(addr)
        fout = fh >= GATE_USD or self.anchors.get(a) == "origin"
        fin = th >= GATE_USD
        if chain and chain != "sol" and not ((fin and fout) if level == "direct" else (fin or fout)):
            f0i, f0o = fin, fout

            def enough(gi, go):
                i9, o9 = f0i or gi >= GATE_USD, f0o or go >= GATE_USD
                return (i9 and o9) if level == "direct" else (i9 or o9)
            cl = self.cluster(chain, a, enough)
            fin = fin or D(cl["in"]) >= GATE_USD
            fout = fout or D(cl["out"]) >= GATE_USD
            g["cl"] = {k: cl.get(k) for k in ("in", "out", "via_in", "via_out", "capped")}
        return (fin and fout) if level == "direct" else (fin or fout)

    def in_ledger(self, chain, txh):
        return self.db.execute("SELECT 1 FROM raw_txs WHERE chain=? AND (txhash=? OR lower(txhash)=?)", (chain, txh, norm(txh))).fetchone() is not None

    def _bridge_lot(self, dst_chain, dst_tx, qty, depth, path, proto=None):
        ops = self.resolve(dst_chain, dst_tx, proto)
        op = next((o for o in ops if o.get("dst_chain") == dst_chain and norm(o.get("dst_tx")) == norm(dst_tx) and o.get("src_tx")), None)
        if not op or not op.get("src_chain") or not op.get("src_tx"):
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge?", "tx": dst_tx}
        path.append({"k": "bridge", "proto": op["proto"], "src": op["src_chain"], "tx": op["src_tx"], "from": op.get("src_from"), "vaa": op.get("id")})
        if self.in_ledger(op["src_chain"], op["src_tx"]):
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "mine", "tx": op["src_tx"], "proto": op["proto"], "src": op["src_chain"]}
        S = op.get("src_from")
        if not S or depth >= MAX_DEPTH or not self.own_ok(S, "source", op["src_chain"]):
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge_gate", "tx": op["src_tx"], "proto": op["proto"],
                    "src": op["src_chain"], "from": S}
        if op["src_chain"] == "sol":
            return self._sol_bridge_src(op, S, qty, depth, path)
        cr = self.receipt(op["src_chain"], op["src_tx"])
        tok = op.get("token") if op.get("token_chain") == op["src_chain"] else None
        dl = evm_owner_deltas(cr, S)
        if not tok and op.get("src_pools"):
            pools = {norm(p) for p in op["src_pools"]}
            sp = {lg["a"] for lg in cr["logs"] if lg["t"][0] == TR and "0x" + lg["t"][1][26:] == norm(S) and "0x" + lg["t"][2][26:] in pools}
            tok = sp.pop() if len(sp) == 1 else None
        if not tok:
            neg = [t for t, v in dl.items() if v < 0]
            tok = neg[0] if len(neg) == 1 else None
        if not tok or dl.get(tok, 0) >= 0:
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge?", "tx": op["src_tx"], "proto": op["proto"], "src": op["src_chain"]}
        sent = Decimal(-dl[tok]) / (Decimal(10) ** self.decimals(op["src_chain"], tok))
        if depth > 1:
            try:
                lots = self._evm_holder_lots(op["src_chain"], S, tok, cr["block"], sent, depth + 1, path, cur=(op["src_tx"], None))
            except ScanCap as ex:
                self.log(f"bridge src cap {short(S)}: {ex}")
                return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge_cap", "tx": op["src_tx"], "proto": op["proto"],
                        "src": op["src_chain"], "from": S, "capped": True}
        else:
            lots = self._evm_holder_lots(op["src_chain"], S, tok, cr["block"], sent, depth + 1, path, cur=(op["src_tx"], None))
        c, cov = pool(lots, sent)
        f = cov / sent if sent > 0 else Decimal(0)
        return {"qty": str(qty), "known": str(D(qty) * f), "cost": str(c), "kind": "bridge", "tx": op["src_tx"], "proto": op["proto"],
                "src": op["src_chain"], "from": S, "sent": str(sent), "srcLots": lots}

    def _sol_bridge_src(self, op, S, qty, depth, path):
        ct = self.sol_tx(op["src_tx"])
        dl, _sol = sol_owner_deltas(ct, S)
        mint = op.get("token") if op.get("token_chain") == "sol" and dl.get(op.get("token") or "", 0) < 0 else None
        if not mint:
            neg = [m for m, v in dl.items() if v < 0 and m != WSOL and m not in _STABLE_MINTS]
            mint = neg[0] if len(neg) == 1 else None
        acct = sol_token_account(ct, mint, S) if mint else None
        if not mint or not acct:
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge?", "tx": op["src_tx"], "proto": op["proto"], "src": "sol"}
        sent = -dl[mint]
        try:
            lots = self._sol_holder_lots(S, mint, acct, op["src_tx"], depth + 1, path, need=sent)
        except ScanCap as ex:
            if depth <= 1:
                raise
            self.log(f"bridge src cap {short(S)}: {ex}")
            return {"qty": str(qty), "known": "0", "cost": "0", "kind": "bridge_cap", "tx": op["src_tx"], "proto": op["proto"],
                    "src": "sol", "from": S, "capped": True}
        c, cov = pool(lots, sent)
        f = cov / sent if sent > 0 else Decimal(0)
        return {"qty": str(qty), "known": str(D(qty) * f), "cost": str(c), "kind": "bridge", "tx": op["src_tx"], "proto": op["proto"],
                "src": "sol", "from": S, "sent": str(sent), "srcLots": lots}

    def _evm_in_lot(self, chain, H, token, inf, depth, path):
        cr = self.receipt(chain, inf["tx"])
        if not cr or cr.get("status") not in ("0x1", 1, None):
            return None
        blk = cr["block"] or inf["block"]
        dl = evm_owner_deltas(cr, H)
        dq = D(dl.get(norm(token), 0)) / (Decimal(10) ** self.decimals(chain, token))
        if dq <= 0:
            return None
        cost = Decimal(0)
        st = {norm(k) for k in _stable_cas(chain)}
        for t, v in dl.items():
            if t in st and v < 0:
                cost += Decimal(-v) / (Decimal(10) ** self.decimals(chain, t))
        nat = Decimal(cr["value"]) / Decimal(10 ** 18) if cr["from"] == norm(H) else Decimal(0)
        w = WRAPPED.get(chain)
        if w and dl.get(w, 0) < 0:
            nat += Decimal(-dl[w]) / Decimal(10 ** 18)
        if nat > 0:
            px = self.native_px(chain, self.block_ts(chain, cr["block"]))
            if px:
                cost += nat * D(px)
            else:
                return {"qty": str(dq), "known": "0", "cost": "0", "kind": "swap?", "tx": inf["tx"], "block": blk}
        if cost > 0:
            return {"qty": str(dq), "known": str(dq), "cost": str(cost), "kind": "swap", "tx": inf["tx"], "chain": chain, "block": blk}
        frm = inf.get("from") or ""
        if frm == ZERO or frm in (self.seed.get("evm_contracts") or {}):
            return dict(self._bridge_lot(chain, inf["tx"], dq, depth, path), block=blk)
        if depth < MAX_DEPTH and frm and frm not in self.mine and self.own_ok(frm, "source", chain):
            try:
                sub = self._evm_holder_lots(chain, frm, token, cr["block"], dq, depth + 1, path, cur=(inf["tx"], H))
            except ScanCap as ex:
                self.log(f"hop cap {short(frm)}: {ex}")
                return {"qty": str(dq), "known": "0", "cost": "0", "kind": "hop_cap", "tx": inf["tx"], "from": frm, "block": blk,
                        "capped": True}
            c, cov = pool(sub, dq)
            return {"qty": str(dq), "known": str(cov), "cost": str(c), "kind": "hop", "tx": inf["tx"], "from": frm, "block": blk}
        return {"qty": str(dq), "known": "0", "cost": "0", "kind": "xfer", "tx": inf["tx"], "from": frm, "block": blk}

    def _evm_holder_lots(self, chain, H, token, before_block, need, depth, path, cur=None):
        need = D(need)
        items = self.evm_inflows(chain, token, H, before_block, need)
        while True:
            lots, seen, sub = [], set(), []
            for inf in items:
                if inf["tx"] in seen:
                    continue
                seen.add(inf["tx"])
                lt = self._evm_in_lot(chain, H, token, inf, depth, sub)
                if lt is not None:
                    lots.append(lt)
            res = self._net_prior_out(chain, H, token, before_block, need, lots,
                                      complete=self.evm_inflows_done(chain, token, H, before_block), cur=cur)
            if res is not None:
                path.extend(sub)
                return res
            if not self.evm_inflows_more(chain, token, H, before_block):
                path.extend(sub)
                return self._net_prior_out(chain, H, token, before_block, need, lots, complete=True, cur=cur)
            st, _k, _o = self._scan_state("to", chain, token, H, before_block)
            items = st["items"]

    def _sol_holder_lots(self, H, mint, acct, before_sig, depth, path, need=None):
        chunks = [self.sol_sigs(acct, before_sig)]
        while True:
            sigs = [s for ch in chunks for s in ch]
            capped = len(chunks[-1]) >= SOL_SIG_PAGE * SOL_SIG_PAGES
            sub = []
            res, more = self._sol_lots_from(H, mint, list(reversed(sigs)), depth, sub, need, capped)
            if not more:
                path.extend(sub)
                return res
            if len(chunks) >= SOL_SIG_CHUNKS:
                raise ScanCap(f"sol {short(acct)} 서명 조회 상한 {len(sigs)}건")
            chunks.append(self.sol_sigs(acct, sigs[-1]["sig"]))

    def _sol_lots_from(self, H, mint, sigs, depth, path, need, capped):
        lots = []
        incomplete, first = False, True
        for s in sigs:
            if s["err"]:
                continue
            ct = self.sol_tx(s["sig"])
            if not ct or ct["err"]:
                continue
            if first:
                first = False
                b0 = sol_owner_pre(ct, H, mint)
                if b0 > 0:
                    lots.append({"qty": str(b0), "known": "0", "cost": "0", "kind": "pre", "tx": s["sig"]})
            dl, dsol = sol_owner_deltas(ct, H)
            dq = dl.get(mint, Decimal(0))
            if dq < 0 and not sol_is_lp(ct, self.seed):
                have = sum((D(x["qty"]) for x in lots), Decimal(0))
                if -dq > have * Decimal("1.001"):
                    incomplete = True
                lots = fifo_take(lots, -dq, have)
                continue
            if dq <= 0:
                continue
            if sol_is_lp(ct, self.seed):
                continue
            proto = sol_bridge_proto(ct, self.seed) or sol_solver(ct, self.seed)
            if proto:
                lots.append(self._bridge_lot("sol", s["sig"], dq, depth, path, proto))
                continue
            cost = Decimal(0)
            for m, v in dl.items():
                if m in _STABLE_MINTS and v < 0:
                    cost += -v
            spent = -dsol - (Decimal(ct["fee"]) / Decimal(10 ** 9) if (ct.get("signers") or [None])[0] == H else Decimal(0))
            if dl.get(WSOL, Decimal(0)) < 0:
                spent += -dl[WSOL]
            if spent > SOL_SPEND_MIN:
                px = self.native_px("sol", ct["ts"])
                if px:
                    cost += spent * D(px)
                elif cost <= 0:
                    lots.append({"qty": str(dq), "known": "0", "cost": "0", "kind": "swap?", "tx": s["sig"]})
                    continue
            if cost > 0:
                lots.append({"qty": str(dq), "known": str(dq), "cost": str(cost), "kind": "swap", "tx": s["sig"], "chain": "sol"})
                continue
            frm = sol_counterparty(ct, mint, H)
            if depth < MAX_DEPTH and frm and frm not in self.mine and self.own_ok(frm, "source", "sol"):
                acct2 = sol_token_account(ct, mint, frm)
                if acct2:
                    try:
                        sub = self._sol_holder_lots(frm, mint, acct2, s["sig"], depth + 1, path, need=dq)
                    except ScanCap as ex:
                        self.log(f"hop cap {short(frm)}: {ex}")
                        lots.append({"qty": str(dq), "known": "0", "cost": "0", "kind": "hop_cap", "tx": s["sig"], "from": frm,
                                     "capped": True})
                        continue
                    c, cov = pool(sub, dq)
                    lots.append({"qty": str(dq), "known": str(cov), "cost": str(c), "kind": "hop", "tx": s["sig"], "from": frm})
                    continue
            lots.append({"qty": str(dq), "known": "0", "cost": "0", "kind": "xfer", "tx": s["sig"], "from": frm})
        res = fifo_take(lots, 0, need) if need is not None and D(need) > 0 else lots
        more = capped and (incomplete or any(x.get("kind") == "pre" for x in res))
        return res, more

    def _arrival_keys(self, chain, txh, token=None, to=None, amount_raw=None, t0=None):
        q = ("SELECT p.source_id, p.location, a.address, p.qty_base FROM postings p JOIN assets a USING(asset_id)"
             " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.leg_kind IN ('acq','move_in') AND p.location LIKE 'wallet:%'")
        if txh:
            rs = self.db.execute(q + " AND p.source_id IN (?, ?)", (chain, txh, norm(txh))).fetchall()
            if token:
                rs = [r for r in rs if norm(r[2]) == norm(token)] or rs
        else:
            rs = [r for r in self.db.execute(q + " AND p.location=? AND p.qty_base=? AND p.event_ts BETWEEN ? AND ?",
                                             (chain, f"wallet:{chain}:{to}", str(amount_raw), int(t0), int(t0) + 172800)).fetchall()
                  if norm(r[2]) == norm(token)]
            if len(rs) != 1:
                return []
        return [arr_key(chain, r[0], r[1].split(":", 2)[2], r[2]) for r in rs]

    def trace_send(self, cand):
        k, chain, tx = cand["key"], cand["chain"], cand["tx"]
        e = {"t": int(time.time())}
        prev = (self.c.get("snd") or {}).get(k) or {}
        try:
            n = 0
            pend = 0
            for op in self.resolve(chain, tx, cand.get("proto")):
                if norm(op.get("src_tx")) != norm(tx) or not op.get("dst_chain"):
                    continue
                if op.get("dst_tx") and self.in_ledger(op["dst_chain"], op["dst_tx"]):
                    keys = self._arrival_keys(op["dst_chain"], op["dst_tx"], op.get("token") if op.get("token_chain") == op["dst_chain"] else None)
                elif op.get("amount_raw") and op.get("to") and op.get("token"):
                    keys = self._arrival_keys(op["dst_chain"], None, op["token"], op["to"], op["amount_raw"], cand["ts"])
                    pend += 0 if keys else 1
                else:
                    keys = []
                    pend += 1 if op.get("dst_tx") else 0
                for ak in keys:
                    self.c["arr"][ak] = {"t": e["t"], "status": "link", "src_chain": chain, "src_tx": norm(tx), "proto": op["proto"],
                                         "id": op.get("id"), "label": label(op["proto"], chain, op["dst_chain"], self.seed)}
                    n += 1
            if n:
                e["status"] = "link"
            elif pend:
                w0 = int(prev.get("w0") or e["t"]) if prev.get("status") == "wait" else e["t"]
                e["w0"] = w0
                e["status"] = "wait" if e["t"] - w0 < WAIT_MAX else "none"
            else:
                e["status"] = "none"
            e["n"] = n
        except Paused as ex:
            e["status"] = "paused"
            e["err"] = _cm9.safe_err(ex)[:200]
        except Budget:
            e["status"] = "budget"
        except Exception as ex:
            e["status"] = "error"
            e["err"] = _cm9.safe_err(ex)[:200]
        self.c["snd"][k] = e
        return e

    def trace(self, cand):
        k, chain, tx, W, tok, qty = cand["key"], cand["chain"], cand["tx"], cand["wallet"], cand["token"], D(cand["qty"])
        e = {"t": int(time.time()), "qty": str(qty), "sym": cand.get("sym")}
        path = []
        try:
            if chain == "sol":
                ct = self.sol_tx(tx)
                if not ct:
                    raise RuntimeError("tx 없음")
                proto = sol_bridge_proto(ct, self.seed)
                solver = sol_solver(ct, self.seed)
                e.update(proto=proto, solver=solver)
                if proto or solver:
                    lot = self._bridge_lot("sol", tx, qty, 1, path, proto or solver)
                    self._finish_bridge(e, lot, chain)
                elif cand.get("stable"):
                    e["status"] = "none"
                else:
                    H = sol_counterparty(ct, tok, W)
                    acct = sol_token_account(ct, tok, H) if H else None
                    self._finish_hop(e, H if acct else None, lambda: self._sol_holder_lots(H, tok, acct, tx, 2, path, need=qty), qty, chain)
            else:
                cr = self.receipt(chain, tx)
                if not cr:
                    raise RuntimeError("영수증 없음")
                senders = evm_token_senders(cr, tok, W) if tok and tok not in ("native", "") else [cr["from"]]
                H = senders[0] if senders else cr["from"]
                bridge = cr["to"] in (self.seed.get("evm_contracts") or {}) or H == ZERO or H in (self.seed.get("evm_contracts") or {})
                solver = (self.seed.get("solvers") or {}).get(cr["from"], {}).get("proto")
                e.update(proto=None, solver=solver)
                if bridge or solver:
                    lot = self._bridge_lot(chain, tx, qty, 1, path, solver or ((self.seed.get("evm_contracts") or {}).get(cr["to"]) or {}).get("proto"))
                    e["proto"] = lot.get("proto") or ((self.seed.get("evm_contracts") or {}).get(cr["to"]) or {}).get("proto")
                    self._finish_bridge(e, lot, chain)
                elif cand.get("stable"):
                    e["status"] = "none"
                else:
                    self._finish_hop(e, H, lambda: self._evm_holder_lots(chain, H, tok, cr["block"], qty, 2, path, cur=(tx, W)), qty, chain)
        except Paused as ex:
            e["status"] = "paused"
            e["err"] = _cm9.safe_err(ex)[:200]
        except Budget:
            e["status"] = "budget"
        except Exception as ex:
            e["status"] = "error"
            e["err"] = _cm9.safe_err(ex)[:200]
        e["path"] = path[:12]
        prev = self.c["arr"].get(k)
        if (isinstance(prev, dict) and prev.get("status") == "ok" and (prev.get("stale") or prev.get("reverify"))
                and e.get("status") not in ("ok", "link", "none", "gate")):
            prev["rt"], prev["rst"] = e["t"], e.get("status")
            if e.get("err"):
                prev["rerr"] = e["err"]
            return prev
        self.c["arr"][k] = e
        return e

    def _finish_bridge(self, e, lot, dst_chain):
        e["proto"] = lot.get("proto") or e.get("proto")
        e["src_chain"], e["src_tx"] = lot.get("src"), lot.get("tx")
        e["label"] = label(e["proto"], lot.get("src"), dst_chain, self.seed)
        if lot["kind"] == "mine":
            e["status"] = "link"
        elif D(lot["known"]) > 0:
            e.update(status="ok", cost=_r(lot["cost"]), cov=_r(lot["known"]), hops=[lot.get("from")] if lot.get("from") else [],
                     via=short(lot.get("from")), lots=[lot])
        else:
            e["status"] = "gate" if lot["kind"] == "bridge_gate" else "none"

    def _finish_hop(self, e, H, lots_fn, qty, chain):
        if not H or H in self.mine:
            e["status"] = "none"
            return
        e["hop"] = H
        if not self.own_ok(H, "direct", chain):
            e["status"] = "gate"
            e["gate"] = self.c["gate"].get(norm(H))
            return
        lots = lots_fn()
        c, cov = pool(lots, qty)
        protos = [x.get("proto") for x in lots if x.get("kind") == "bridge" and D(x.get("known")) > 0]
        srcs = sorted({x.get("src") for x in lots if x.get("kind") == "bridge" and D(x.get("known")) > 0})
        hops = [H] + sorted({x.get("from") for x in lots if x.get("from")})
        e["via"] = short(H)
        e["label"] = (label(protos[0], "/".join(CHAIN_KO.get(s, s) for s in srcs) if len(srcs) > 1 else srcs[0], chain, self.seed)
                      + f" · 내 지갑 경유 {short(H)}") if protos else f"내 지갑 경유 {short(H)} · 매수 원가"
        e["lots"] = lots
        e["hops"] = [h for h in hops if h]
        if any(x.get("capped") for x in lots):
            e["capped"] = True
        if cov > 0:
            e.update(status="ok" if cov >= qty * Decimal("0.999") else "partial", cost=_r(c), cov=_r(cov))
            if e["status"] == "partial":
                e["status"] = "ok"
                e["partial"] = True
        else:
            e["status"] = "none"


_STABLE_MINTS = set()


def _stable_cas(chain):
    try:
        import pricing
        return (pricing.STABLE_CAS.get(chain) or {}).keys()
    except Exception:
        return ()


def _init_mints():
    try:
        import pricing
        _STABLE_MINTS.update(pricing.STABLE_MINTS.keys())
    except Exception:
        _STABLE_MINTS.update({"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"})


_init_mints()


def anchors_from_state(state_dir, conn, cfg):
    out = {}

    def put(a, why):
        a = norm(a)
        if a.startswith("0x") and len(a) == 42 and a != ZERO:
            out.setdefault(a, why)
    try:
        with open(os.path.join(state_dir, "deposit_addresses.json"), encoding="utf-8") as f:
            for r in (json.load(f) or {}).get("records") or []:
                if isinstance(r, dict) and not r.get("tag"):
                    put(r.get("address"), "deposit")
    except (OSError, ValueError, AttributeError):
        pass
    for e in cfg.get("exchange_addresses") or []:
        if isinstance(e, dict) and not e.get("memo") and not e.get("tag"):
            put(e.get("address"), "deposit")
    try:
        for (a,) in conn.execute("SELECT address FROM exchange_addresses WHERE memo IS NULL OR memo=''"):
            put(a, "deposit")
    except Exception:
        pass
    dep, wd = set(), set()
    try:
        for kind, pl in conn.execute("SELECT kind, payload FROM raw_ex WHERE kind IN ('deposit','withdraw')"):
            try:
                tx = norm(str(json.loads(pl).get("txid") or ""))
            except (ValueError, AttributeError):
                continue
            if tx:
                (dep if kind == "deposit" else wd).add(tx)
    except Exception:
        pass
    try:
        with open(os.path.join(state_dir, "tx_origin_cache.json"), encoding="utf-8") as f:
            oc = json.load(f) or {}
    except (OSError, ValueError):
        oc = {}
    hot = {norm(v.get("from")) for tx, v in oc.items() if isinstance(v, dict) and norm(tx) in wd and v.get("from")}
    for tx, v in oc.items():
        if isinstance(v, dict) and v.get("from") and norm(tx) in dep and norm(tx) not in wd and norm(v["from"]) not in hot:
            out[norm(v["from"])] = "origin"
    return out


def exchange_addrs_from_state(state_dir, conn, cfg):
    out = set()

    def put(a):
        a = norm(a)
        if a.startswith("0x") and len(a) == 42 and a != ZERO:
            out.add(a)
    try:
        with open(os.path.join(state_dir, "deposit_addresses.json"), encoding="utf-8") as f:
            for r in (json.load(f) or {}).get("records") or []:
                if isinstance(r, dict):
                    put(r.get("address"))
    except (OSError, ValueError, AttributeError):
        pass
    for e in cfg.get("exchange_addresses") or []:
        if isinstance(e, dict):
            put(e.get("address"))
    try:
        for (a,) in conn.execute("SELECT address FROM exchange_addresses"):
            put(a)
    except Exception:
        pass
    wd = set()
    try:
        for (pl,) in conn.execute("SELECT payload FROM raw_ex WHERE kind='withdraw'"):
            try:
                tx = norm(str(json.loads(pl).get("txid") or ""))
            except (ValueError, AttributeError):
                continue
            if tx:
                wd.add(tx)
    except Exception:
        pass
    try:
        with open(os.path.join(state_dir, "tx_origin_cache.json"), encoding="utf-8") as f:
            oc = json.load(f) or {}
    except (OSError, ValueError):
        oc = {}
    for tx, v in oc.items():
        if isinstance(v, dict) and v.get("from") and norm(tx) in wd:
            put(v["from"])
    return out


def run_once(cfg, state_dir, db_path, base_dir, rows_cands, limit=1, budget=300, log=None, px=None, sleep=0.35, skip_gids=None):
    import sqlite3
    cache = load_cache(state_dir)
    seed = load_seed(base_dir)
    conn = sqlite3.connect(_cm9.sqlite_ro_uri(db_path), uri=True, timeout=10)
    done = []
    try:
        anchors = anchors_from_state(state_dir, conn, cfg)
        cex = exchange_addrs_from_state(state_dir, conn, cfg)
        for cand in rows_cands[:limit]:
            tr = Tracer(cfg, cache, conn, seed, px=px, budget=budget, sleep=sleep, log=log, anchors=anchors, skip_gids=skip_gids, cex=cex)
            e = tr.trace_send(cand) if cand.get("kind") == "send" else tr.trace(cand)
            done.append((cand["key"], e.get("status"), tr.calls))
            _save(state_dir, cache)
    finally:
        conn.close()
    return done


def _save(state_dir, cache):
    p = os.path.join(state_dir, CACHE_NAME)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, p)


def _cli():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import common
    import db as dbm
    import pricing
    cfg = common.read_json(common.CONFIG_PATH, {})
    cache = load_cache(common.STATE_DIR)
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        for k, e in sorted(cache["snd"].items(), key=lambda kv: -float(kv[1].get("t") or 0)):
            print("send", e.get("status"), k[:90], e.get("n"), e.get("err") or "")
        for k, e in sorted(cache["arr"].items(), key=lambda kv: -float(kv[1].get("t") or 0)):
            print(e.get("status"), k[:90], e.get("sym"), e.get("qty"), e.get("cost"), e.get("label"), e.get("err") or "")
        return
    conn = dbm.open_db(common.DB_PATH, readonly=True)
    import web
    b = web.StateBuilder.__new__(web.StateBuilder)
    rows = web.StateBuilder._load(b, conn)
    stab = {r[0] for r in conn.execute("SELECT group_id FROM asset_groups WHERE name IN ('USDT','USDC','DAI','USDE','USDG','FDUSD','BUSD','USD1','PYUSD')")}
    ex = set()
    for (p,) in conn.execute("SELECT payload FROM raw_ex WHERE kind='withdraw'"):
        try:
            t = str(json.loads(p).get("txid") or "")
        except ValueError:
            continue
        if t:
            ex.add(t)
            ex.add(t.lower())
    conn.close()
    cands = send_candidates(rows, cache, load_seed(common.BASE_DIR)) + candidates(rows, cache, frozenset(ex), frozenset(stab))
    if "--key" in sys.argv:
        kk = sys.argv[sys.argv.index("--key") + 1]
        cands = [c for c in cands if kk in c["key"]]
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 1
    bud = int(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 300
    print(f"후보 {len(cands)}건 · 이번 {min(lim, len(cands))}건")
    px = pricing.PxCache(os.path.join(common.STATE_DIR, "xchain_px_cache.json"))
    for r in run_once(cfg, common.STATE_DIR, common.DB_PATH, common.BASE_DIR, cands, limit=lim, budget=bud,
                      log=lambda m: print("  ·", m), px=px):
        print(r)
    px.flush()


if __name__ == "__main__":
    _cli()
