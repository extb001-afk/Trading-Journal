#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check, W, SOLW

import itertools
import json
import os

import common
W1 = "0x" + "e7" * 20
SOLW2 = "So2" + "2" * 41
cfg = json.load(open(os.path.join(T.TMP, "config.json")))
cfg["wallets"] += [{"type": "evm", "chain": "eth", "address": W1}, {"type": "sol", "address": SOLW2}]
json.dump(cfg, open(os.path.join(T.TMP, "config.json"), "w"))
import core
assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
B, R = "0x" + "b2" * 20, "0x" + "c3" * 20
TKA, TKB = "0x" + "a" * 40, "0x" + "b" * 40
TS = 1790000500
SHAPES = ("es", "rpc", "bs_list", "full")


class Reader:
    def __init__(self, recs):
        self.recs = recs

    def read_batch(self, seg, off):
        return [(r, 0, i + 1) for i, r in enumerate(self.recs)], 0, len(self.recs)

    def gc(self, seg, off):
        pass


def leg_row(shape, lg, h):
    if lg[0] == "it":
        _k, v, to = lg
        if shape in ("es", "rpc"):
            return {"from": R, "to": to, "value": str(v)}
        return {"from": {"hash": R}, "to": {"hash": to}, "value": str(v), "success": True, "type": "call", "index": 0,
                "block_number": 500, "transaction_hash": h}
    _k, ca, v, to = lg
    if shape in ("full", "bs_list"):
        r = {"from": {"hash": B}, "to": {"hash": to}, "token": {"address_hash": ca, "symbol": "T", "decimals": "6", "type": "ERC-20"},
             "total": {"value": str(v), "decimals": "6"}, "log_index": 3 if ca == TKA else 4, "block_number": 500}
        if shape == "bs_list":
            r["transaction_hash"] = h
        return r
    return {"from": B, "to": to, "token": {"address": ca, "symbol": "T", "decimals": 6, "type": "ERC-20"}, "total": {"value": str(v)}}


def snap(shape, h, legs):
    full = shape == "full"
    tx = {"hash": h, "from": ({"hash": B} if full else B), "to": ({"hash": R} if full else R), "value": "0",
          "fee": {"value": "0"}, "status": "ok", "raw_input": "0x01", "timestamp": TS, "block_number": 500, "block_hash": "0x" + "d" * 64}
    out = {"tx": tx, "token_transfers": [leg_row(shape, lg, h) for lg in legs if lg[0] == "tt"],
           "internal": [leg_row(shape, lg, h) for lg in legs if lg[0] == "it"]}
    if shape == "rpc":
        tx["synth"] = "rpc"
    if shape == "bs_list":
        tx["synth"] = "bs_list"
        out["src"] = "bs_list"
    return out


def legs_of(c, ns, h):
    return sorted((str(r[0]), str(r[1]).lower(), int(r[2])) for r in c.conn.execute(
        "SELECT COALESCE(a.address, a.kind), p.location, p.qty_base FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
        " WHERE p.source_kind='chain_tx' AND p.source_ns=? AND p.source_id=?", (ns, h)).fetchall())


def done_ok(pid):
    d = common.read_json(os.path.join(common.STATE_DIR, "poison_replayed.json"), {}) or {}
    return bool((d.get(pid) or {}).get("ok"))


def poison_has(pid):
    try:
        lines = open(os.path.join(common.STATE_DIR, "poison.jsonl"), encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return False
    for ln in lines:
        rec = (json.loads(ln) or {}).get("rec") or {}
        if pid in ((rec.get("ts_fix") or {}).get("poison_ids") or []):
            return True
    return False


c = core.Core(common.load_config())
c.conn.commit()
assert W1.lower() in c.my_wallets.get("eth", set()), c.my_wallets


def posted(lg):
    if lg[0] == "it":
        return ("native", f"wallet:eth:{lg[2].lower()}", int(lg[1]))
    return (lg[1].lower(), f"wallet:eth:{lg[3].lower()}", int(lg[2]))


L1 = ("tt", TKA, 1, W)
LI = ("it", 5, W)
n_case = n_ok = 0
bad = []
kinds = {}
for i, (so, sn, addw, old_k, new_k) in enumerate(itertools.product(
        SHAPES, SHAPES, (False, True), ("L1", "none"), ("L1", "L2", "L1+L2", "none", "L1+int"))):
    L2 = ("tt", TKB, 2, W1 if addw else W)
    old_legs = [L1] if old_k == "L1" else []
    new_legs = {"L1": [L1], "L2": [L2], "L1+L2": [L1, L2], "none": [], "L1+int": [L1, LI]}[new_k]
    o9, n9 = set(old_legs), set(new_legs)
    old_list, new_list = so != "full", sn != "full"
    if old_list and new_list:
        want = ("ok", o9 | n9)
    elif old_list:
        want = ("ok", n9) if o9 <= n9 else ("hold", o9)
    elif n9 <= o9:
        want = ("ok", o9)
    elif not new_list and o9 <= n9:
        want = ("ok", n9)
    elif {x for x in n9 if x[0] == "tt"} <= o9:
        want = ("ok", o9 | n9)
    else:
        want = ("hold", o9)
    h = "0x" + ("%064x" % (0xF0000 + i))
    pid = "q%015d" % i
    wl_new = [W, W1] if addw else [W]
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h, "wallets": [W],
                                    "snapshot": snap(so, h, old_legs), "ts": 1}]), 0, 0)
    base = legs_of(c, "eth", h)
    fix = {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": h, "wallets": wl_new, "snapshot": snap(sn, h, new_legs), "ts": 2,
           "ts_fix": {"poison_ids": [pid], "src": "block_ts", "block": 500}}
    c._drain_stream("evm", Reader([fix]), 0, 0)
    got = legs_of(c, "eth", h)
    ok1 = done_ok(pid)
    c._drain_stream("evm", Reader([fix]), 0, 0)
    again = legs_of(c, "eth", h)
    exp = sorted(posted(lg) for lg in want[1])
    wrow = json.loads(c.conn.execute("SELECT wallets FROM raw_txs WHERE chain='eth' AND txhash=?", (h,)).fetchone()[0])
    if want[0] == "ok":
        good = ok1 and got == exp and again == exp and (not addw or W1.lower() in [x.lower() for x in wrow])
    else:
        good = (not ok1) and not done_ok(pid) and got == base and again == base and poison_has(pid)
    lossless = (not ok1) or set(exp_ for exp_ in (posted(lg) for lg in o9 | n9)) <= set(got)
    n_case += 1
    kinds[want[0]] = kinds.get(want[0], 0) + 1
    if good and lossless:
        n_ok += 1
    else:
        bad.append((so, sn, "add_w" if addw else "-", old_k, new_k, want[0], "해소" if ok1 else "미해소", got, exp))
check(f"[G] EVM 시각 보강본 조합 {n_case}개(해소 {kinds.get('ok', 0)} · 격리 유지 {kinds.get('hold', 0)}) 전부 불변식대로 · 두 번 = 무변",
      not bad, f"실패 {len(bad)}건: " + "; ".join(str(b) for b in bad[:6]))
hit = [b for b in bad if b[0] == "bs_list" and b[1] == "es" and b[2] == "add_w" and b[4] == "L2"]
check("[G] 저장 블록스카웃 목록(W0) × 보강 이더스캔 목록(W0·W1) · 레그 다름 = 합집합·해소(보강 레그 버리지 않음)", not hit, hit)
mixed = [b for b in bad if b[0] != "full" and b[1] != "full" and b[0] != b[1] and b[2] == "add_w"]
check("[G] 새 지갑 관점 동반 · 서로 다른 목록 모양 전부 = 합집합", not mixed, mixed[:4])
holds = [b for b in bad if b[5] == "hold"]
check("[G] 모순 조합(완전 상세가 다른 레그를 모름) = 격리 유지(성공 표시 없음 · 원장 무변 · 격리 파일 보존)", not holds, holds[:4])

hR = "0x" + "%064x" % 0xFEEE
L2R = ("tt", TKB, 2, W)
c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hR, "wallets": [W], "snapshot": snap("full", hR, [L1]), "ts": 1}]), 0, 0)
fixR = {"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": hR, "wallets": [W], "snapshot": snap("es", hR, [L2R]), "ts": 2,
        "ts_fix": {"poison_ids": ["rorig0000000001"], "src": "block_ts", "block": 500}}
c._drain_stream("evm", Reader([fixR]), 0, 0)
_pz = os.path.join(common.STATE_DIR, "poison.jsonl")
held = [json.loads(x) for x in open(_pz, encoding="utf-8").read().splitlines()] if os.path.exists(_pz) else []
held = [e for e in held if (e.get("rec") or {}).get("txhash") == hR]
check("[R] 모순 보강본 = 격리 파일에 사유와 함께 보존", len(held) == 1 and "레그 유실 위험" in held[0].get("err", ""), held[:1])
if held:
    rid = core.Core.poison_id(held[0])
    json.dump({"ids": [rid]}, open(c.POISON_REQ_PATH, "w"))
    c.poison_replay_pass()
    d9 = common.read_json(c.POISON_DONE_PATH, {})
    check("[R] 저장본 그대로 재시도 = 또 실패 기록 · 원래 id 미해소", (d9.get(rid) or {}).get("ok") is False and not done_ok("rorig0000000001"), d9.get(rid))
    c.conn.execute("UPDATE raw_txs SET snapshot=? WHERE chain='eth' AND txhash=?", (json.dumps(snap("full", hR, [L1, L2R])), hR))
    c.conn.commit()
    json.dump({"ids": [rid]}, open(c.POISON_REQ_PATH, "w"))
    c.poison_replay_pass()
    check("[R] 저장본이 전 레그를 갖게 된 뒤 재시도 = 성공 + 원래 격리 id 해소(via ts_fix)", done_ok(rid) and done_ok("rorig0000000001"))
else:
    check("[R] 재시도(격리 보존본이 없어 못 함)", False)

D1 = {"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "5", "owner": SOLW}
D2 = {"asset": "Mint" + "M" * 40, "symbol": "TK", "decimals": 6, "delta": "3", "owner": SOLW2}
D3 = {"asset": "native", "symbol": "SOL", "decimals": 9, "delta": "7", "owner": SOLW}


def srec(sig, deltas, err=False, **kw):
    r = {"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": sig, "slot": 900, "ts": TS, "fee_lamports": 0,
         "fee_payer_mine": False, "fee_payer": None, "wallets": sorted({d["owner"] for d in deltas}) or [SOLW], "deltas": deltas,
         "counterparties": [], "has_program": False, "err": err}
    r.update(kw)
    return r


def key(d):
    return (d["owner"], d["asset"], d["delta"])


sbad = []
s_n = 0
for j, (new_k, errd, rp) in enumerate(itertools.product(("same", "sub", "super", "cross", "none"), (False, True), (False, True))):
    old_d = [D1, D2] if new_k == "sub" else [D1]
    new_d = {"same": [D1], "sub": [D1], "super": [D1, D2], "cross": [D3], "none": []}[new_k]
    lo, ln = {key(d) for d in old_d}, {key(d) for d in new_d}
    if errd:
        want = "hold"
    elif ln <= lo:
        want = "keep"
    elif lo <= ln:
        want = "new"
    else:
        want = "hold"
    sig = "S%087d" % j
    pid = "s%015d" % j
    c._drain_stream("sol", Reader([srec(sig, old_d)]), 0, 0)
    base = legs_of(c, "sol", sig)
    kw = {"ts_fix": {"poison_ids": [pid], "src": "block_ts", "block": 900}}
    if rp:
        kw["repersp"] = True
    fix = srec(sig, new_d, err=errd, **kw)
    c._drain_stream("sol", Reader([fix]), 0, 0)
    got = legs_of(c, "sol", sig)
    ok1 = done_ok(pid)
    c._drain_stream("sol", Reader([fix]), 0, 0)
    again = legs_of(c, "sol", sig)
    s_n += 1
    if want == "keep":
        good = ok1 and got == base and again == base
    elif want == "new":
        good = ok1 and got != base and again == got and len(got) >= len(base)
    else:
        good = (not ok1) and got == base and again == base and poison_has(pid)
    if not good:
        sbad.append((new_k, "err다름" if errd else "-", "repersp" if rp else "-", want, "해소" if ok1 else "미해소", base, got))
check(f"[S] 솔라나 시각 보강본 조합 {s_n}개 전부 불변식대로(부분 = 그대로 해소 · 초과 = 재기장 해소 · 엇갈림/실패 여부 다름 = 격리 유지)",
      not sbad, f"실패 {len(sbad)}건: " + "; ".join(str(b) for b in sbad[:6]))
c.conn.close()
T.finish()
