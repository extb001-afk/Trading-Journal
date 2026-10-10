"""Links token-sale participation to acquisition cost."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import netpace
import common

T_BID_SUBMITTED = "0x650baad5cd8ca09b8f580be220fa04ce2ba905a041f764b6a3fe2c848eb70540"
T_BID_EXITED = "0x054fe6469466a0b4d2a6ae4b100e5f9c494c958f04b4000f44d470088dd97930"
T_TOKENS_CLAIMED = "0x880f2ef2613b092f1a0a819f294155c98667eb294b7e6bf7a3810278142c1a1c"
ZERO = "0x" + "0" * 40
CACHE_NAME = "sale_bids.json"
WINDOW_SEC = 60 * 86400
RECHECK_OPEN_SEC = 6 * 3600
RECHECK_DONE_SEC = 30 * 86400
LABEL = "토큰 세일 참여 (Uniswap CCA)"
STABLE_CUR = {"USDC", "USDT", "USDT0", "DAI", "USDS", "USDE", "PYUSD", "FDUSD", "USDG", "USD1", "RLUSD", "USDC.E", "USDBC"}
_HEX40 = re.compile(r"^0x[0-9a-f]{40}$")


def _addr(x) -> str:
    if isinstance(x, dict):
        x = x.get("hash") or x.get("address_hash") or x.get("address")
    s = str(x or "").strip().lower()
    return s if _HEX40.match(s) else ""


def _dec(x):
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


_SEED = None


def load_seed(base_dir=None) -> dict:
    global _SEED
    if _SEED is not None and base_dir is None:
        return _SEED
    bd = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import common
    raw = common.seed_json("sale_contracts.json", {}, base_dir=bd)
    raw = raw if isinstance(raw, dict) else {}
    seed = {"factories": {_addr(a) for a in (raw.get("cca_factories") or []) if _addr(a)},
            "chains": [str(c) for c in (raw.get("chains") or ["eth", "base", "arbitrum"])],
            "auctions": {str(k).lower(): v for k, v in (raw.get("auctions") or {}).items() if isinstance(v, dict)},
            "redeem": {str(k).lower(): v for k, v in (raw.get("redeem") or {}).items() if isinstance(v, dict)}}
    if base_dir is None:
        _SEED = seed
    return seed


def http_get_json(url: str, timeout: float = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "tj-bot/0.1 (personal trade journal)", "Accept": "application/json"})
    netpace.wait(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(common.read_capped(r).decode())
    except urllib.error.HTTPError as e:
        netpace.note_error(url, e)
        raise
    if isinstance(d, dict) and not isinstance(d.get("result"), list):
        m9 = f"{d.get('message') or ''} {d.get('result') or ''}"
        if netpace.note_error(url, m9):
            raise OSError(f"rate limit: {m9[:80]}")
    return d


def _topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def _get_logs(get, base, topic0, owner, address=None):
    u = (f"{base}/api?module=logs&action=getLogs&fromBlock=0&toBlock=latest&topic0={topic0}"
         f"&topic2={_topic(owner)}&topic0_2_opr=and" + (f"&address={address}" if address else ""))
    d = get(u)
    res = d.get("result") if isinstance(d, dict) else None
    if isinstance(res, list):
        return res
    msg = str((d or {}).get("message") or "") if isinstance(d, dict) else ""
    if "No records" in msg or "no logs" in msg.lower():
        return []
    raise RuntimeError(f"getLogs 응답 이상: {str(d)[:160]}")


def _words(data: str):
    h = str(data or "")[2:]
    return [int(h[i:i + 64], 16) for i in range(0, len(h) - 63, 64)]


def _tok(t: dict) -> dict:
    tk = t.get("token") or {}
    tot = t.get("total") or {}
    dec = tk.get("decimals") if tk.get("decimals") is not None else tot.get("decimals")
    try:
        dec = int(dec)
    except (TypeError, ValueError):
        dec = 18
    return {"addr": _addr(tk.get("address_hash") or tk.get("address")), "sym": str(tk.get("symbol") or "?")[:24], "dec": dec,
            "raw": int(tot.get("value") or 0) if str(tot.get("value") or "0").isdigit() else 0,
            "from": _addr(t.get("from")), "to": _addr(t.get("to"))}


def _tx_transfers(get, base, tx):
    d = get(f"{base}/api/v2/transactions/{tx}/token-transfers")
    return [_tok(t) for t in ((d or {}).get("items") or []) if isinstance(t, dict)]


def _auction_ok(get, base, chain, auction, seed):
    if f"{chain}:{auction}" in seed["auctions"]:
        return True, "seed"
    d = get(f"{base}/api/v2/addresses/{auction}") or {}
    cr = _addr(d.get("creator_address_hash"))
    if cr and cr in seed["factories"]:
        return True, "factory"
    return False, f"creator {cr or '?'} name {str(d.get('name') or '')[:40]}"


REDEEM_PAGES = 10
REDEEM_BURNS = 20


def _detect_redeem(get, base, owner, receipt):
    burns, url = [], f"{base}/api/v2/addresses/{owner}/token-transfers?type=ERC-20&token={receipt}"
    for _p in range(REDEEM_PAGES):
        d = get(url) or {}
        for t in (d.get("items") or []):
            if isinstance(t, dict):
                b = _tok(t) | {"tx": t.get("transaction_hash") or t.get("tx_hash")}
                if b["from"] == owner and b["to"] == ZERO and b["addr"] == receipt:
                    burns.append(b)
        np_ = d.get("next_page_params") if isinstance(d, dict) else None
        if not np_ or len(burns) >= REDEEM_BURNS:
            break
        url = (f"{base}/api/v2/addresses/{owner}/token-transfers?type=ERC-20&token={receipt}&"
               + "&".join(f"{k}={v}" for k, v in np_.items()))
    burns = burns[:REDEEM_BURNS]
    got, burnt, meta, txs = {}, Decimal(0), None, []
    for b in burns:
        rest = [t for t in _tx_transfers(get, base, b["tx"]) if t["to"] == owner and t["addr"] and t["addr"] != receipt]
        if len({t["addr"] for t in rest}) != 1:
            continue
        burnt += Decimal(b["raw"]) / (Decimal(10) ** b["dec"])
        for t in rest:
            meta = meta or t
            got[t["addr"]] = got.get(t["addr"], Decimal(0)) + Decimal(t["raw"]) / (Decimal(10) ** t["dec"])
        txs.append(b["tx"])
    if len(got) != 1 or burnt <= 0:
        return None
    (to, amt), = got.items()
    return {"to": to, "sym": meta["sym"], "decimals": meta["dec"], "ratio": str(amt / burnt), "tx": txs}


def fetch_owner(get, base, chain, owner, seed, now=None) -> dict:
    owner = _addr(owner)
    now = int(now or time.time())
    rec = {"t": now, "chain": chain, "owner": owner, "bids": [], "auctions": {}}
    subs = _get_logs(get, base, T_BID_SUBMITTED, owner)
    for lg in subs:
        a = _addr(lg.get("address"))
        w = _words(lg.get("data"))
        if not a or len(w) < 2:
            continue
        rec["bids"].append({"auction": a, "id": int(lg["topics"][1], 16), "amount": str(w[1]),
                            "bid_tx": str(lg.get("transactionHash") or "").lower(), "bid_ts": int(str(lg.get("timeStamp") or "0x0"), 16)})
    for a in sorted({b["auction"] for b in rec["bids"]}):
        ok, why = _auction_ok(get, base, chain, a, seed)
        info = {"ok": ok, "why": why}
        rec["auctions"][a] = info
        if not ok:
            continue
        mine = [b for b in rec["bids"] if b["auction"] == a]
        for lg in _get_logs(get, base, T_BID_EXITED, owner, a):
            w = _words(lg.get("data"))
            bid = int(lg["topics"][1], 16)
            for b in mine:
                if b["id"] == bid and len(w) >= 2:
                    b.update({"filled": str(w[0]), "refunded": str(w[1]), "exit_tx": str(lg.get("transactionHash") or "").lower(),
                              "exit_ts": int(str(lg.get("timeStamp") or "0x0"), 16)})
        for lg in _get_logs(get, base, T_TOKENS_CLAIMED, owner, a):
            bid = int(lg["topics"][1], 16)
            for b in mine:
                if b["id"] == bid:
                    b.update({"claim_tx": str(lg.get("transactionHash") or "").lower(), "claim_ts": int(str(lg.get("timeStamp") or "0x0"), 16)})
        cur = None
        for t in _tx_transfers(get, base, mine[0]["bid_tx"]):
            if t["to"] == a and t["addr"]:
                cur = {"addr": t["addr"], "sym": t["sym"], "dec": t["dec"]}
                break
        info["currency"] = cur or {"addr": "", "sym": "ETH", "dec": 18}
        cl = next((b for b in mine if b.get("claim_tx")), None)
        tok = None
        if cl:
            for t in _tx_transfers(get, base, cl["claim_tx"]):
                if t["from"] == a and t["to"] == owner and t["addr"]:
                    tok = {"addr": t["addr"], "sym": t["sym"], "dec": t["dec"]}
                    break
        info["token"] = tok
        if tok:
            rd = seed["redeem"].get(f"{chain}:{tok['addr']}")
            if rd and _addr(rd.get("to")):
                info["redeem"] = {"to": _addr(rd["to"]), "sym": str(rd.get("sym") or "?"), "decimals": int(rd.get("decimals") or 18),
                                  "ratio": str(rd.get("ratio") or "1"), "src": "seed"}
            else:
                det = _detect_redeem(get, base, owner, tok["addr"])
                if det:
                    info["redeem"] = det | {"src": "detected"}
    return rec


def needs_refresh(rec, now=None, hot=False) -> bool:
    now = int(now or time.time())
    if hot and isinstance(rec, dict):
        return now - int(rec.get("t") or 0) >= RECHECK_OPEN_SEC
    if not isinstance(rec, dict) or rec.get("err"):
        return not isinstance(rec, dict) or now - int(rec.get("t") or 0) >= RECHECK_OPEN_SEC
    age = now - int(rec.get("t") or 0)
    open_ = False
    for b in rec.get("bids") or []:
        inf = (rec.get("auctions") or {}).get(b.get("auction")) or {}
        if not inf.get("ok"):
            continue
        if "filled" not in b or "claim_ts" not in b:
            open_ = True
        elif not inf.get("redeem") and now - int(b.get("claim_ts") or 0) < 45 * 86400:
            open_ = True
    return age >= (RECHECK_OPEN_SEC if open_ else RECHECK_DONE_SEC)


def build_lots(cache: dict, price_fn=None, off=(), seed=None) -> list:
    seed = seed or load_seed()
    off = {str(x) for x in (off or ())}
    lots = []
    for key in sorted((cache or {}).get("owners") or {}):
        rec = cache["owners"][key]
        if not isinstance(rec, dict) or rec.get("err"):
            continue
        chain, owner = rec.get("chain"), _addr(rec.get("owner"))
        for a, inf in sorted((rec.get("auctions") or {}).items()):
            if not inf.get("ok") or not inf.get("token"):
                continue
            bids = [b for b in rec.get("bids") or [] if b.get("auction") == a and "filled" in b]
            if not bids:
                continue
            cur, tok, rd = inf.get("currency") or {}, inf["token"], inf.get("redeem")
            cdec, tdec = int(cur.get("dec") or 18), int(tok.get("dec") or 18)
            paid = sum((Decimal(b["amount"]) for b in bids), Decimal(0)) / (Decimal(10) ** cdec)
            refund = sum((Decimal(b.get("refunded") or 0) for b in bids), Decimal(0)) / (Decimal(10) ** cdec)
            filled = sum((Decimal(b.get("filled") or 0) for b in bids), Decimal(0)) / (Decimal(10) ** tdec)
            if filled <= 0:
                continue
            csym = str(cur.get("sym") or "?").upper()
            bad9 = any(not (Decimal(0) <= Decimal(b.get("refunded") or 0) <= Decimal(b["amount"])) for b in bids)
            paid_usd = refund_usd = Decimal(0)
            ok = not bad9
            if csym in STABLE_CUR:
                paid_usd, refund_usd = paid, refund
            else:
                for b in bids:
                    px = price_fn(csym, int(b.get("bid_ts") or 0)) if price_fn else None
                    if not px:
                        ok = False
                        break
                    paid_usd += Decimal(b["amount"]) / (Decimal(10) ** cdec) * Decimal(str(px))
                    refund_usd += Decimal(b.get("refunded") or 0) / (Decimal(10) ** cdec) * Decimal(str(px))
            cost = paid_usd - refund_usd if ok else None
            if cost is not None and cost <= 0:
                cost = None
            ratio = _dec((rd or {}).get("ratio")) or Decimal(1)
            qty = filled * ratio if rd else filled
            final = {"addr": rd["to"], "sym": rd.get("sym") or "?"} if rd else {"addr": tok["addr"], "sym": tok.get("sym") or "?"}
            t_claim = max([int(b.get("claim_ts") or b.get("exit_ts") or 0) for b in bids] or [0])
            lid = f"{chain}:{a}:{owner}"
            senders = {owner, a} | ({tok["addr"]} if rd else set())
            bid_d = []
            for b in bids:
                am9, rf9 = Decimal(b["amount"]), Decimal(b.get("refunded") or 0)
                bid_d.append({"id": b.get("id"), "bid_tx": str(b.get("bid_tx") or "").lower(), "exit_tx": str(b.get("exit_tx") or "").lower(),
                              "amount": am9 / (Decimal(10) ** cdec),
                              "refunded": rf9 / (Decimal(10) ** cdec) if Decimal(0) <= rf9 <= am9 else None})
            lots.append({"id": lid, "chain": chain, "auction": a, "bidder": owner, "bids": len(bids),
                         "cur_addr": _addr(cur.get("addr")), "bid_d": bid_d,
                         "ratio": ratio if rd else Decimal(1), "filled": filled,
                         "label": str((seed["auctions"].get(f"{chain}:{a}") or {}).get("label") or LABEL),
                         "cur": csym, "paid": paid, "refund": refund, "paid_usd": paid_usd, "refund_usd": refund_usd,
                         "cost": cost, "qty": qty, "unit": None if cost is None else cost / qty, "token": final["addr"], "sym": str(final["sym"]).upper(),
                         "receipt": tok["addr"] if rd else None, "receipt_sym": tok.get("sym") if rd else None,
                         "senders": senders, "t0": min(int(b.get("bid_ts") or 0) for b in bids), "t_claim": t_claim,
                         "t_end": t_claim + WINDOW_SEC, "bid_tx": [b["bid_tx"] for b in bids],
                         "claim_tx": sorted({b.get("claim_tx") for b in bids if b.get("claim_tx")}), "off": lid in off})
    lots.sort(key=lambda l9: (l9["t0"], l9["id"]))
    return lots


def collect_inflows(conn, lots, origin_cache, my_addrs) -> tuple:
    out, need = [], set()
    live = list(lots)
    if not live:
        return out, need
    by_chain = {}
    rcpt = set()
    for l9 in live:
        by_chain.setdefault(l9["chain"], set()).add(l9["token"])
        if l9.get("receipt"):
            by_chain[l9["chain"]].add(l9["receipt"])
            rcpt.add((l9["chain"], l9["receipt"]))
    for ch, toks in sorted(by_chain.items()):
        toks = sorted(toks)
        q9 = ("SELECT p.posting_id, p.source_ns, p.source_id, p.event_ts, p.qty_base, p.location, a.decimals, a.address, a.symbol"
              " FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
              " WHERE p.leg_kind='acq' AND p.event IN ('PROGRAM_IN','TRANSFER_IN') AND p.cost_usd IS NULL"
              " AND a.kind='token' AND a.chain=? AND lower(a.address) IN (" + ",".join("?" * len(toks)) + ")"
              " ORDER BY p.event_ts, p.posting_id")
        for r in conn.execute(q9, (ch, *toks)).fetchall():
            w9 = str(r["location"] or "").split(":")[-1].lower()
            row = conn.execute("SELECT json_extract(snapshot,'$.token_transfers') AS tt FROM raw_txs WHERE chain=? AND txhash IN (?, ?)",
                               (r["source_ns"], r["source_id"], str(r["source_id"]).lower())).fetchone()
            try:
                tts = json.loads(row["tt"]) if row and row["tt"] else []
            except (ValueError, TypeError):
                tts = []
            snd = {_tok(t)["from"] for t in tts if isinstance(t, dict)
                   and _tok(t)["addr"] == str(r["address"]).lower() and _tok(t)["to"] == w9}
            if len(snd) != 1:
                continue
            qty = Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 18))
            out.append({"pid": r["posting_id"], "kind": "chain", "chain": ch, "token": str(r["address"]).lower(),
                        "sym": str(r["symbol"] or "").upper(), "qty": qty, "ts": int(r["event_ts"]), "sender": snd.pop(),
                        "ref": str(r["source_id"]), "to": w9,
                        "rcpt": (ch, str(r["address"]).lower()) in rcpt})
    syms = sorted({l9["sym"] for l9 in live if l9["sym"]})
    if syms:
        dep_tx = {}
        for rf in conn.execute("SELECT exchange, uuid, payload FROM raw_ex WHERE kind='deposit'"
                               " GROUP BY exchange, uuid HAVING revision = MAX(revision)").fetchall():
            try:
                pw = json.loads(rf["payload"])
            except (ValueError, TypeError):
                continue
            t9 = str(pw.get("txid") or "")
            if t9.startswith("0x"):
                dep_tx[rf["uuid"]] = t9.lower()
        q9 = ("SELECT p.posting_id, p.source_id, p.event_ts, p.qty_base, a.decimals, a.symbol FROM postings p"
              " JOIN assets a ON a.asset_id = p.asset_id"
              " WHERE p.leg_kind='move_in' AND p.event IN ('EXF_DEPOSIT','EX_DEPOSIT') AND a.kind='exchange_currency'"
              " AND upper(a.symbol) IN (" + ",".join("?" * len(syms)) + ") ORDER BY p.event_ts, p.posting_id")
        chains9 = [c9[0] for c9 in conn.execute("SELECT DISTINCT chain FROM raw_txs").fetchall()]
        for r in conn.execute(q9, syms).fetchall():
            tx = dep_tx.get(r["source_id"])
            if not tx:
                continue
            if chains9 and conn.execute("SELECT 1 FROM raw_txs WHERE chain IN (" + ",".join("?" * len(chains9)) + ") AND txhash=? LIMIT 1",
                                        (*chains9, tx)).fetchone():
                continue
            oc = (origin_cache or {}).get(tx)
            if not isinstance(oc, dict) or not oc.get("from"):
                need.add(tx)
                continue
            snd = _addr(oc.get("from"))
            if not snd or snd in my_addrs:
                continue
            qty = Decimal(int(r["qty_base"])) / (Decimal(10) ** int(r["decimals"] if r["decimals"] is not None else 8))
            out.append({"pid": r["posting_id"], "kind": "ex", "chain": str(oc.get("chain") or ""), "token": _addr(oc.get("to")),
                        "sym": str(r["symbol"] or "").upper(), "qty": qty, "ts": int(r["event_ts"]), "sender": snd, "ref": tx,
                        "src": r["source_id"]})
    out.sort(key=lambda x: (x["ts"], x["pid"]))
    return out, need


def match(lots, inflows) -> dict:
    left = {l9["id"]: l9["qty"] for l9 in lots}
    links = {}
    per_auction = {}
    for l9 in lots:
        if not l9["off"]:
            per_auction[(l9["chain"], l9["auction"])] = per_auction.get((l9["chain"], l9["auction"]), 0) + 1

    def same_asset(x, l9):
        if x["kind"] == "chain":
            return x["chain"] == l9["chain"] and x["token"] == l9["token"]
        return x["kind"] == "ex" and x["sym"] == l9["sym"] and x["chain"] == l9["chain"]
    sent = {}
    for x in inflows:
        for l9 in lots:
            if not l9["off"] and x["sender"] == l9["bidder"] and x["ts"] >= l9["t0"] and same_asset(x, l9):
                sent[l9["id"]] = sent.get(l9["id"], Decimal(0)) + x["qty"]
    loose = {l9["id"] for l9 in lots if sent.get(l9["id"], Decimal(0)) <= l9["qty"] * Decimal("1.001")}
    for x in sorted(inflows, key=lambda x: (x["ts"], x["pid"])):
        if x.get("rcpt") and x["kind"] == "chain":
            hit = None
            for l9 in lots:
                if l9["off"] or left[l9["id"]] <= 0 or not l9.get("receipt"):
                    continue
                if x["chain"] != l9["chain"] or x["token"] != l9["receipt"] or x.get("to") != l9["bidder"]:
                    continue
                if str(x["ref"]).lower() not in {str(t).lower() for t in l9.get("claim_tx") or ()}:
                    continue
                rt = l9.get("ratio") or Decimal(1)
                take_f = min(x["qty"] * rt, left[l9["id"]])
                left[l9["id"]] -= take_f
                un9 = l9.get("unit")
                links[x["pid"]] = {"lot": l9["id"], "take": take_f / rt, "qty": x["qty"], "unit": None if un9 is None else un9 * rt,
                                   "cost": None if un9 is None else take_f * un9, "ts": x["ts"], "ref": x["ref"], "kind": x["kind"],
                                   "sender": x["sender"], "rcpt": True, "take_final": take_f}
                hit = l9
                break
            if hit:
                continue
        for l9 in lots:
            if l9["off"] or left[l9["id"]] <= 0:
                continue
            if not same_asset(x, l9):
                continue
            if x["sender"] not in l9["senders"] or x["ts"] < l9["t0"]:
                continue
            if x["ts"] > l9["t_end"] and not (x["sender"] == l9["bidder"] and l9["id"] in loose):
                continue
            if x["sender"] != l9["bidder"]:
                if x["kind"] == "chain" and x.get("to") and x["to"] != l9["bidder"]:
                    continue
                if x["kind"] == "ex" and per_auction.get((l9["chain"], l9["auction"]), 0) > 1:
                    continue
            take = min(x["qty"], left[l9["id"]])
            left[l9["id"]] -= take
            links[x["pid"]] = {"lot": l9["id"], "take": take, "qty": x["qty"], "unit": l9["unit"], "cost": None if l9["unit"] is None else take * l9["unit"],
                               "ts": x["ts"], "ref": x["ref"], "kind": x["kind"], "sender": x["sender"]}
            break
    return links


def redeem_pairs(lots, seed=None) -> dict:
    seed = seed or load_seed()
    out = {}
    for k, v in (seed.get("redeem") or {}).items():
        ch, _, a = str(k).partition(":")
        to, rt = _addr(v.get("to")), _dec(v.get("ratio") or "1")
        if ch and _addr(a) and to and rt and rt > 0:
            out[(ch, _addr(a))] = {"to": to, "ratio": rt}
    for l9 in lots or ():
        if l9.get("receipt") and l9.get("token") and (l9.get("ratio") or 0) > 0:
            out[(l9["chain"], l9["receipt"])] = {"to": l9["token"], "ratio": l9["ratio"]}
    return out


def desc(lot) -> str:
    un9 = lot.get("unit")
    return (f"토큰 세일 매수 · 참여 ${float(lot['paid_usd']):,.2f} · 환불 ${float(lot['refund_usd']):,.2f}"
            + (" · 단가 미확인" if un9 is None else f" · 단가 ${float(un9):,.6g}") + f" ({lot['label']})")


def owner_queue(conn, chains, wallets, origin_cache, prio_syms=(), limit=2000) -> list:
    seen, out = set(), []

    def add(ch, a):
        if a and a != ZERO and (ch, a) not in seen:
            seen.add((ch, a)); out.append((ch, a))
    for ch in chains:
        for a in sorted(wallets.get(ch) or ()):
            add(ch, a)
    for tx, oc in sorted((origin_cache or {}).items()):
        if isinstance(oc, dict) and oc.get("chain") in chains:
            add(oc["chain"], _addr(oc.get("from")))
    prio = {str(x).upper() for x in (prio_syms or ())}
    rows = conn.execute(
        "SELECT p.source_ns AS ch, p.location AS loc, lower(a.address) AS tok, upper(a.symbol) AS sym,"
        " json_extract(r.snapshot,'$.token_transfers') AS tt"
        " FROM postings p JOIN assets a ON a.asset_id = p.asset_id JOIN raw_txs r ON r.chain = p.source_ns AND r.txhash = p.source_id"
        " WHERE p.leg_kind='acq' AND p.event IN ('PROGRAM_IN','TRANSFER_IN') AND p.cost_usd IS NULL AND a.kind='token'"
        " AND p.source_ns IN (" + ",".join("?" * len(chains)) + ") ORDER BY p.event_ts DESC, p.posting_id DESC", tuple(chains))
    later = []
    for r in rows:
        w9 = str(r["loc"] or "").split(":")[-1].lower()
        try:
            tts = json.loads(r["tt"]) if r["tt"] else []
        except (ValueError, TypeError):
            continue
        for t in tts:
            if not isinstance(t, dict):
                continue
            tk = _tok(t)
            if tk["addr"] == r["tok"] and tk["to"] == w9:
                if r["sym"] in prio:
                    add(r["ch"], tk["from"])
                else:
                    later.append((r["ch"], tk["from"]))
    for ch, a in later:
        add(ch, a)
    return out[:limit]


def heuristic_scan(conn, stable_syms, days=30) -> list:
    pays = conn.execute(
        "SELECT p.source_ns AS ch, p.event_ts AS ts, p.location AS loc, upper(a.symbol) AS sym, a.kind AS kind,"
        " p.qty_base AS q, a.decimals AS dec, p.source_id AS tx"
        " FROM postings p JOIN assets a ON a.asset_id = p.asset_id"
        " WHERE p.leg_kind='move_in' AND p.event='TRANSFER_OUT' AND p.location LIKE 'out:%'").fetchall()
    by_dest = {}
    for r in pays:
        if not (r["kind"] == "native" or r["sym"] in stable_syms):
            continue
        dest = str(r["loc"]).split(":")[-1].lower()
        by_dest.setdefault((r["ch"], dest), []).append(r)
    if not by_dest:
        return []
    out = []
    rows = conn.execute(
        "SELECT p.source_ns AS ch, p.source_id AS tx, p.event_ts AS ts, p.location AS loc, lower(a.address) AS tok,"
        " upper(a.symbol) AS sym, p.qty_base AS q, a.decimals AS dec, json_extract(r.snapshot,'$.token_transfers') AS tt"
        " FROM postings p JOIN assets a ON a.asset_id = p.asset_id JOIN raw_txs r ON r.chain = p.source_ns AND r.txhash = p.source_id"
        " WHERE p.leg_kind='acq' AND p.event='PROGRAM_IN' AND p.cost_usd IS NULL AND a.kind='token'")
    for r in rows:
        if r["sym"] in stable_syms:
            continue
        try:
            tts = json.loads(r["tt"]) if r["tt"] else []
        except (ValueError, TypeError):
            continue
        for t in tts:
            tk = _tok(t) if isinstance(t, dict) else None
            if not tk or tk["addr"] != r["tok"]:
                continue
            ps = [p for p in by_dest.get((r["ch"], tk["from"]), ()) if 0 <= r["ts"] - p["ts"] <= days * 86400]
            if ps:
                out.append({"chain": r["ch"], "contract": tk["from"], "sym": r["sym"], "in_tx": r["tx"], "in_ts": r["ts"],
                            "qty": str(Decimal(int(r["q"])) / (Decimal(10) ** int(r["dec"] or 18))),
                            "paid": [{"sym": p["sym"], "qty": str(Decimal(abs(int(p["q"]))) / (Decimal(10) ** int(p["dec"] or 18))),
                                      "tx": p["tx"], "ts": p["ts"]} for p in ps][:5]})
                break
    return out
