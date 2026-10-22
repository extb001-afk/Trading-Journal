#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check, Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import address_codec as ac  # noqa: E402
import chain_registry as reg  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402

TS = 1_700_000_000
TON1 = N.OWN["ton"][0]
TON_RAW = ac.ton_raw(TON1)
TAP = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
BTC_T = reg.btc_source({"mode": "address", "address": TAP})["key"]
SUI1 = N.OWN["sui"][0]
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["wallets"] = [dict(w, chain=w.get("chain") or ("sol" if w.get("type") == "sol" else "eth")) for w in cfg["wallets"]]
cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(TON1), "label": "AuditTonOne"},
                        {"chain": "btc", "mode": "address", "address": TAP, "label": "AuditTaproot"},
                        {"chain": "sui", "address": SUI1, "label": "AuditSuiOne"}]
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())


def feed(stream, recs):
    c._drain_stream(stream, Reader([json.loads(json.dumps(r)) for r in recs]), 0, 0)


H_TON = "e2" * 32
U_TON = TON1 + ".7." + H_TON
U_BT, U_SUI = "e5" * 32, "Sx9" + "c" * 40
feed("ton", [N.rec("ton", U_TON, TS + 200, [(TON1, "native", 7_000_000_000)], txhash=H_TON)])
feed("btc", [N.rec("btc", U_BT, TS + 300, [(BTC_T, "native", 10_000)])])
feed("sui", [N.rec("sui", U_SUI, TS + 100, [(SUI1, "native", 5_000_000_000)])])
c.conn.commit()
c.conn.close()

import acct_norm  # noqa: E402
import pricing  # noqa: E402
import search_index as si  # noqa: E402
import web  # noqa: E402


def _no_price(url, *a, **k):
    raise OSError("시험: 시세 받기 없음")


pricing._gj = _no_price
acct_norm.FxBook.candle = lambda self, sym, ts: None
web.Spot.dex_pending = lambda self, c9, ca: False
web.Spot.ex_pending = lambda self, ex: False
SPATH = os.path.join(T.TMP, "search_wl.db")
H_EVM = "0x" + "e1" * 32
W_EVM = _ingest.W
EVM_DOC = {"kind": "tx", "key": "tx:eth:" + H_EVM, "grp": "tx:eth", "title": "tx evm", "sub": "", "body": "ETH", "date": "2023-11-14",
           "ts": TS + 50, "chain": "eth", "etype": "transfer", "addr": W_EVM, "tx": H_EVM, "syms": ["ETH"], "chains": ["eth"], "wals": [W_EVM]}
web.BUILDER = b = web.StateBuilder()
st = b.build()
ix = si.Indexer(state_fn=lambda: (st, getattr(b, "_day_idx", None)), chain_names=web.CHAIN_NAME, path=SPATH, ledger_path=paths.DB_PATH,
                sleep=lambda s9: None)
ix.tick()
ix.ix._insert([EVM_DOC])


def q(text):
    return si.search(text, path=SPATH, budget_s=5)


def ids(r):
    return sorted(i.get("id") for g in (r.get("groups") or []) if g.get("kind") == "tx" for i in g.get("items") or [])


ALL = sorted(["tx:ton:" + U_TON, "tx:btc:" + U_BT, "tx:sui:" + U_SUI, "tx:eth:" + H_EVM])
check("전제: 날짜 조건만 = 대상 거래 4건(TON·Taproot·Sui·EVM)", ids(q("after:2020-01-01")) == ALL, ids(q("after:2020-01-01")))
check("전제: TON raw 66자 · Taproot 62자", len(TON_RAW) == 66 and len(TAP) == 62, (len(TON_RAW), len(TAP)))

for nm, addr, want in (("WL1 TON raw", TON_RAW, "tx:ton:" + U_TON), ("WL2 Taproot", TAP, "tx:btc:" + U_BT)):
    r = q(f"wallet:{addr} after:2020-01-01")
    check(f"{nm} 양의 wallet + 날짜 = 대상 1건(ignored 없음)", ids(r) == [want] and not r.get("ignored"), (ids(r), r.get("ignored")))
    r = q(f"-wallet:{addr} after:2020-01-01")
    check(f"{nm} 음의 wallet + 날짜 = 나머지 3건(ignored 없음)", ids(r) == [x for x in ALL if x != want] and not r.get("ignored"),
          (ids(r), r.get("ignored")))

LONG = TAP + "x" * (si.WALLET_VAL_MAX - len(TAP) + 1) if hasattr(si, "WALLET_VAL_MAX") else TAP + "x" * 80
for sign in ("", "-"):
    pq = si.parse_query(f"{sign}wallet:{LONG}")
    check(f"WL3 {sign or '+'}wallet: 상한 넘는 값 = 명시적 거절(ignored 이유 · 필터에 잘린 값 없음)",
          any("길" in (x.get("why") or "") for x in pq["ignored"]) and "wallet" not in pq["filters"] and "wallet" not in pq["neg"],
          (pq["ignored"], pq["filters"], pq["neg"]))
pq = si.parse_query(f"wallet:{TON_RAW}")
check("WL4 파서가 TON raw 를 자르지 않음", pq["filters"].get("wallet") == [TON_RAW] or pq["filters"].get("wallet") == TON_RAW, pq["filters"])
r = q("wallet:AuditTonOne")
check("WL4 이름 wallet:AuditTonOne = 1건", ids(r) == ["tx:ton:" + U_TON], ids(r))
check("바깥 연결 0", not T.NET_TRIES, T.NET_TRIES)
T.finish()
