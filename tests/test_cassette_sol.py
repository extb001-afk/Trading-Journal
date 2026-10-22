#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _cassette as C  # noqa: E402

C.freeze()
import json  # noqa: E402
import os  # noqa: E402

O = "so1wa11et" + "9" * 35
A = "so1ata" + "8" * 38
M = "so1mint" + "7" * 37
X = "so1xch" + "6" * 38
TOKENKEG = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM = "11111111111111111111111111111111"
SOL_KEY = "casSOLkey01"
RPC = "https://sol-node.cassette.invalid/?api-key=" + SOL_KEY


def sig(i):
    return "5" * 80 + "sigaaaa" + str(i)


SIG = {"nat": sig(1), "tok": sig(2), "nat2": sig(3)}
SLOT = {"nat": 300_000_000, "tok": 300_000_100, "nat2": 300_000_400}
BT = {"nat": int(C.NOW) - 7200, "tok": int(C.NOW) - 3600, "nat2": int(C.NOW) - 600}
LIVE = {"nat2": False}


def tx_native(k, lamports):
    return {"slot": SLOT[k], "blockTime": BT[k],
            "meta": {"err": None, "fee": 5000, "preBalances": [5_000_000_000, 1_000_000_000],
                     "postBalances": [5_000_000_000 - lamports - 5000, 1_000_000_000 + lamports],
                     "preTokenBalances": [], "postTokenBalances": [], "innerInstructions": []},
            "transaction": {"signatures": [SIG[k]], "message": {"accountKeys": [{"pubkey": X, "signer": True, "writable": True},
                                                                               {"pubkey": O, "signer": False, "writable": True}],
                                                                "instructions": [{"programId": SYSTEM, "program": "system",
                                                                                  "parsed": {"type": "transfer", "info": {"source": X, "destination": O,
                                                                                                                          "lamports": lamports}}}]}}}


def tx_token():
    return {"slot": SLOT["tok"], "blockTime": BT["tok"],
            "meta": {"err": None, "fee": 5000, "preBalances": [1_000_000_000, 2_039_280], "postBalances": [999_995_000, 2_039_280],
                     "preTokenBalances": [{"accountIndex": 1, "mint": M, "owner": O, "uiTokenAmount": {"amount": "0", "decimals": 6}}],
                     "postTokenBalances": [{"accountIndex": 1, "mint": M, "owner": O, "uiTokenAmount": {"amount": "4000000", "decimals": 6}}],
                     "innerInstructions": []},
            "transaction": {"signatures": [SIG["tok"]], "message": {"accountKeys": [{"pubkey": X, "signer": True, "writable": True},
                                                                                   {"pubkey": A, "signer": False, "writable": True}],
                                                                    "instructions": [{"programId": TOKENKEG, "program": "spl-token"}]}}}


def respond(rq):
    assert rq.host == "sol-node.cassette.invalid", rq.url
    b = rq.json()
    m, p = b["method"], b.get("params")

    def ok(r):
        return {"jsonrpc": "2.0", "id": b.get("id"), "result": r}
    if m == "getTokenAccountsByOwner":
        v = [{"pubkey": A, "account": {"lamports": 2_039_280, "owner": TOKENKEG}}] if p[1].get("programId") == TOKENKEG else []
        return ok({"context": {"slot": 300_000_500}, "value": v})
    if m == "getSignaturesForAddress":
        who, opt = p[0], (p[1] if len(p) > 1 else {})
        keys = (["nat2"] if LIVE["nat2"] else []) + ["nat"] if who == O else ["tok"] if who == A else []
        if opt.get("until"):
            keys = keys[:keys.index(next(k for k in keys if SIG[k] == opt["until"]))] if any(SIG[k] == opt["until"] for k in keys) else keys
        return ok([{"signature": SIG[k], "slot": SLOT[k], "blockTime": BT[k], "err": None, "confirmationStatus": "finalized"} for k in keys])
    if m == "getTransaction":
        k = next(k for k in SIG if SIG[k] == p[0])
        return ok(tx_token() if k == "tok" else tx_native(k, 100_000_000 if k == "nat" else 50_000_000))
    if m == "getAsset":
        return ok({"id": M, "content": {"metadata": {"symbol": "TSTS", "name": "Test Sol Token"}}, "token_info": {"decimals": 6, "symbol": "TSTS"}})
    if m == "getSlot":
        return ok(300_000_500)
    raise AssertionError("모르는 메서드 " + m)


CFG = {"backfill_months": 5, "wallets": [{"type": "sol", "chain": "sol", "address": O, "label": "w"}], "chains": {},
       "sol": {"rpc": RPC, "stake": False}}
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f)
import config, paths  # noqa: E402
import bf_engine  # noqa: E402
import sol_watch  # noqa: E402
from inbox import SegmentWriter  # noqa: E402

cas = C.Cassette("sol_rpc", secrets={"sol_key": SOL_KEY}, responder=respond)


def scenario():
    paths.ensure_dirs()
    cfg = config.load_config()
    bf_engine.configure(cfg)
    wallets = [w["address"] for w in cfg["wallets"] if w.get("type") == "sol"]
    w = sol_watch.SolWatcher(cfg, wallets, SegmentWriter(os.path.join(paths.INBOX_DIR, "sol")))
    w.prune_progress()
    r1 = sol_watch.run_cycle(w)
    LIVE["nat2"] = True
    C.CLOCK.now += 60
    r2 = sol_watch.run_cycle(w)
    return [r1, r2]


if cas.ready(T):
    out, why = cas.run(scenario)
    T.chk(why is None and out == [True, True], "두 주기 정상 끝", [why, out])
    snap = C.snap_tree(paths.STATE_DIR)
    recs = [r for k, v in snap.items() if k.startswith("inbox/sol/") for r in v]
    T.chk(sorted(r.get("txhash") for r in recs) == sorted(SIG.values()), "inbox sol = 네이티브 2 · SPL 1", [r.get("txhash") for r in recs])
    cas.golden(T, snap)
    cas.check(T)
T.finish()
