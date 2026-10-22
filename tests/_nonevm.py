import _harness as T  # noqa: F401

OWN = {
    "tron": ["41" + "11" * 20, "41" + "12" * 20],
    "sui": ["0x" + "21" * 32, "0x" + "22" * 32],
    "ton": ["0_" + "31" * 32, "0_" + "32" * 32],
}
EXT = {"tron": "41" + "99" * 20, "sui": "0x" + "99" * 32, "ton": "0_" + "99" * 32}
BTC_ADDR = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
BTC_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
TOK = {"tron": "41" + "a1" * 20, "sui": "0x" + "a1" * 32 + "::coin_a::COINA", "ton": "0:" + "a1" * 32}


def asset(a):
    if a == "native":
        return {"kind": "native"}
    _k, ident, sym, dec = a
    return {"kind": "token", "id": ident, "symbol": sym, "decimals": dec}


def rec(chain, uid, ts, deltas, fees=(), owners=None, moves=(), failed=False, hint="transfer", trusted=False,
        trace_complete=True, height=100, txhash=None):
    owners = list(owners if owners is not None else sorted({o for o, _a, _d in deltas} | {p for p, _x in fees if p != "external"}))
    return {"v": 1, "kind": "chain_delta_tx", "chain": chain, "network": "mainnet", "tx_uid": uid, "txhash": txhash or uid, "ts": int(ts),
            "order": {"height": height, "checkpoint": None, "lt": None, "index": 0},
            "finality": {"state": "finalized", "blockhash": None, "evidence": "synthetic"},
            "execution": {"state": "failed" if failed else "success", "trace_complete": trace_complete},
            "owners": owners, "ownership_version": "t",
            "deltas": [{"owner": o, "asset": asset(a), "delta_base": str(d)} for o, a, d in deltas],
            "fees": [{"payer": p, "asset": {"kind": "native"}, "amount_base": str(x), "component": "network_fee", "included_in_deltas": True}
                     for p, x in fees],
            "movements": [{"id": f"m{i}", "asset": asset(a), "from": f, "to": t, "amount_base": str(x)} for i, (a, f, t, x) in enumerate(moves)],
            "classification": {"hint": hint, "trusted": trusted, "evidence": "synthetic"},
            "completeness": {"history": True, "details": True, "balances": True, "reasons": []},
            "source": {"provider": "synthetic", "parser_version": 1, "observed_at": int(ts), "payload_digest": "0" * 32}}
