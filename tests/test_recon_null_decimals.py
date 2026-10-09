#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W = "0x" + "a1" * 20
CFG = {"chains": {"base": {"discovery": "rpc", "conf_depth": 12, "blocks_per_day": 43200, "rpcs": ["https://rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "base", "address": W}, {"type": "evm", "chain": "bsc", "address": W}],
       "native_symbol": {"base": "ETH", "bsc": "BNB"}, "backfill_months": 5, "bsc": {"detail_rpcs": ["https://bscrpc.invalid"]}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import recon

assert T.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
chk = T.chk
TOK6 = "0x" + "c6" * 20
TOKP = "0x" + "c7" * 20
TOKR = "0x" + "c8" * 20
TOK8 = "0x" + "c9" * 20
TOKC = "0x" + "ca" * 20
DEC = {TOK6: 6, TOKP: 6, TOK8: 8, TOKC: 6}
BAL = {TOK6: 5 * 10 ** 6, TOKP: 7 * 10 ** 6, TOKR: 123, TOK8: 9 * 10 ** 8, TOKC: 3 * 10 ** 6}
SEEN = {"dec": set()}


def fake_rpc_any(urls, method, params, check=None, tries=None, sleep=None, timeout=25.0):
    if method == "eth_blockNumber":
        return 1000
    if method == "eth_getBlockByNumber":
        return 1790000000
    if method == "eth_getCode":
        return "0x6080"
    if method == "eth_getBalance":
        return 0
    raise AssertionError("예상 밖 RPC " + method)


def fake_mc(urls, blk, items, mc, sleep=None):
    out = {}
    for key, ca, _data in items:
        if key[0] == "bal" and ca in BAL:
            out[key] = BAL[ca].to_bytes(32, "big")
        elif key[0] == "dec":
            SEEN["dec"].add(ca)
            if ca in DEC:
                out[key] = DEC[ca].to_bytes(32, "big")
    return out


recon._rpc_any = fake_rpc_any
recon._mc_call = fake_mc
c = core.Core(common.load_config())
for ca, d in ((TOK6, None), (TOKP, None), (TOKR, None), (TOK8, 8), (TOKC, None)):
    c.conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed) VALUES ('token','base',?,?,?,0)", (ca, "T" + ca[2:4], d))
aidp = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TOKP,)).fetchone()[0]
for ca in (TOK6, TOKP, TOKR, TOK8, TOKC):
    a9 = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (ca,)).fetchone()[0]
    if ca != TOK6:
        c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event,"
                       " classifier_ver) VALUES ('chain_tx','base',?,0,1789000000,?,?,'1','acq','TRANSFER_IN',1)", ("0x" + ca[2:6] * 16, a9, f"wallet:base:{W}"))
c.conn.commit()
json.dump({TOKC: 6}, open(os.path.join(common.STATE_DIR, "rpc_token_meta_base.json"), "w"))
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"), {W: 900})
a6 = c.conn.execute("SELECT asset_id FROM assets WHERE address=?", (TOK6,)).fetchone()[0]

cap = {}
_real_fetch = recon.fetch_evm_rpc_balances


def cap_fetch(rpcs, wallets, cas, **kw):
    cap["cas"] = dict(cas)
    kw["wallet_cas"] = {str(W).lower(): {TOK6, TOKP, TOKR, TOK8, TOKC}}
    return _real_fetch(rpcs, wallets, cas, **kw)


recon.fetch_evm_rpc_balances = cap_fetch
bal = c._recon_fetch_plan("base", "evm", [W])()
cas9 = cap.get("cas") or {}
chk(cas9.get(TOK6, (0, 0))[1] is None and cas9.get(TOKR, (0, 0))[1] is None,
    "D1 EVM 대사 재료: 저장 자릿수 없음 = None(종전 18)", {k[:6]: v for k, v in cas9.items()})
chk(cas9.get(TOKC, (0, 0))[1] == 6 and cas9.get(TOK8, (0, 0))[1] == 8, "D1 수집기 RPC 캐시 6 · 저장 8 = 그 값", {k[:6]: v for k, v in cas9.items()})
got_b = {}
recon.fetch_bsc_balances = lambda rpcs, wallets, cas: got_b.update(cas) or {"per_wallet": {}}
TOKB = "0x" + "cb" * 20
c.conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed) VALUES ('token','bsc',?,'TB',NULL,0)", (TOKB,))
c._recon_fetch_plan("bsc", "bsc", [W])()
chk(got_b.get(TOKB) == ("TB", None), "D1 BSC 대사 재료도 저장 자릿수 없음 = None(종전 18)", got_b)

meta = bal.get("_meta") or {}
chk(meta.get(TOK6) == ("T" + TOK6[2:4], 6) and meta.get(TOKP, (0, 0))[1] == 6, "D2 같은 블록 decimals() = 6 (조회 결과 _meta)", meta)
chk(TOK8 not in SEEN["dec"] and TOKC not in SEEN["dec"] and {TOK6, TOKP, TOKR} <= SEEN["dec"],
    "D5 저장 자릿수 있는 토큰(캐시 포함) = decimals() 조회 안 함 · 없는 것만", sorted(x[:6] for x in SEEN["dec"]))
chk(meta.get(TOKR, ("?", "?"))[1] is None and BAL[TOKR] == (bal.get("per_wallet") or {}).get(W, {}).get(("token", TOKR)),
    "D4 decimals() 못 읽음 = 자릿수 None · 잔고는 그대로 대사 재료", (meta.get(TOKR), (bal.get("per_wallet") or {}).get(W)))
c._recon_onchain("base", bal)
c.conn.commit()


def dec_of(ca):
    return c.conn.execute("SELECT decimals FROM assets WHERE address=?", (ca,)).fetchone()[0]


iss = (common.read_json(c.DEC_ISSUES_PATH, {}) or {}).get("items") or {}
chk(dec_of(TOK6) == 6, "D2 기장 전 NULL 자산 = 6 저장(종전 18)", dec_of(TOK6))
c.asset_id("token", "base", TOK6, symbol="T6", decimals=6)
iss = (common.read_json(c.DEC_ISSUES_PATH, {}) or {}).get("items") or {}
chk(str(a6) not in iss, "D2 뒤이은 수집기 관측 6 = 충돌 없음", iss)
chk(dec_of(TOKP) is None and (iss.get(str(aidp)) or {}).get("kind") == "pending",
    "D3 이미 기장된 NULL 자산 = '채움 대기'(18 저장 · 충돌 아님)", (dec_of(TOKP), iss.get(str(aidp))))
chk(dec_of(TOKR) is None, "D4 decimals() 못 읽은 자산 = NULL 그대로", dec_of(TOKR))
chk(not any((v or {}).get("kind") == "conflict" for v in iss.values()), "D2 '자리수 다름' 0건", iss)
c.conn.close()
T.finish()
