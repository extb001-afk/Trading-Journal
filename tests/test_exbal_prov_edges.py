#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W = "0x" + "3c" * 20
USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 2},
          open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import exprov  # noqa: E402
import flowev  # noqa: E402
import histcurve  # noqa: E402
import hl_spot  # noqa: E402
import netpace  # noqa: E402
import web  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
NOW = int(time.time())
E8 = 10 ** 8
T.patch_moved("dm", lambda *a, **k: None)
for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)
netpace.wait = lambda url, now=None, sleep=None: None
C = core.Core(config.load_config())
px = {"ETH": 3000.0}
json.dump({"usd": px, "usd_ts": {k: NOW for k in px}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {f"okx:{k}": v for k, v in px.items()}, "ex_ts": {f"okx:{k}": NOW for k in px}}, open(paths.state("spot.json"), "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
web.pricing._gj = lambda url, timeout=10.0: None
histcurve.DAYCLOSE.lookup = lambda spec, iso, now=None, w=0.0, ask=True, old=False: (None, "pending")
histcurve.DAYCLOSE.lookup._tj_test_mock = True
statefile.atomic_write_json(paths.state("ui_prefs.json"), {"plans": {}, "ignored": []})


def build():
    for p9 in (paths.state("daily_cache.json"), paths.state("daily_px.json")):
        try:
            os.remove(p9)
        except FileNotFoundError:
            pass
    b = web.StateBuilder()
    b.skip_gen_check = True
    conn = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        return b._build(conn)["fields"]
    finally:
        conn.close()


def total(f):
    return round(sum(float(x.get("qty") or 0) * float(x.get("price") or 0) for x in (f.get("stables") or []) + (f.get("coins") or [])), 2)


statefile.atomic_write_json(os.path.join(S, "exf_balances_okx.json.view"),
                         {"ts": NOW - 30, "balances": {"ETH": 2.0}, "debts": {"USDT": -3000.0}, "sources": ["spot", "loan"]})
f1 = build()
chk(abs(total(f1) - (6000 - 3000)) < 0.02, "R1 원장에 없는 순부채(USDT −3,000)도 총자산에서 뺌 = ETH 6,000 − 3,000", [total(f1)])
neg1 = [x for x in f1.get("stables") or [] if str(x.get("key")) == "pvx:okx:USDT"]
chk(len(neg1) == 1 and abs(float(neg1[0]["qty"]) + 3000) < 1e-6 and "빌린 몫" in str(neg1[0]["locs"][0].get("sub")), "R1 음수 행 = '빌린 몫'", neg1)
os.remove(os.path.join(S, "exf_balances_okx.json.view"))

json.dump({"eth": {"mode": "chain", "at": NOW - 100, "t1": NOW - 99, "bts": NOW - 100, "req": [W],
                   "wallets": {W: {"native": "0", "tok": {USDT_ETH: ["0", "USDT", 6]}, "q": [USDT_ETH]}}}},
          open(os.path.join(S, "prov_bal.json"), "w"))
statefile.atomic_write_json(os.path.join(S, "exf_balances_hyperliquid.json.view"), {"ts": NOW - 50, "balances": {"USDC": 10.0}})
sb = web.StateBuilder()
conn = dbm.open_db(paths.DB_PATH, readonly=True)
try:
    cs, xs = T.safe(sb._prov_seen, conn, {}) if True else (None, None)
finally:
    conn.close()
norm = web.xfer_match.norm_addr
e_l = {"state": "pending", "cls": "wallet", "addr": W, "net": "ETH", "sym": "LINK", "start": NOW - 1000, "src": "바이낸스"}
e_u = dict(e_l, sym="USDT")
cov = lambda e: bool(T.safe(exprov.covered, e, chain_seen=cs, ex_seen=xs, chain_of=web.depaddr.chain_of, norm=norm) is True)
chk(not cov(e_l), "R2 빠른 판이 안 본 토큰(LINK)으로 가는 전송 중 = 받는 쪽이 셈 아님(종전대로 더함)", cs)
chk(cov(e_u), "R2 본 검증 스테이블(USDT) = 받는 쪽 지금 잔고가 셈(가산 안 함)", cs)
chk(isinstance(xs, dict) and "hyperliquid" in xs, "R3 Hyperliquid 첫 대사 전 잔고 = 전송 중·입금 대기 판정 재료(_prov_seen)", xs)
os.remove(os.path.join(S, "prov_bal.json"))

aid = C.svc_exf._exf_asset("hyperliquid", "USDC")
C.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
               " leg_kind, event, classifier_ver) VALUES ('exchange','hyperliquid:withdraw','hw1',0,?,?,'exchange:hyperliquid',?,NULL,NULL,'move_out','EXF_WITHDRAW',?)",
               (NOW - 86400 * 3, aid, str(-5000 * E8), core.CLASSIFIER_VER))
C._bump_position(aid, -5000 * E8, "exchange:hyperliquid")
C.conn.commit()
statefile.atomic_write_json(os.path.join(S, "exf_balances_hyperliquid.json.view"), {"ts": NOW - 50, "balances": {"USDC": -1000.0}})
f4 = build()
pv4 = f4.get("prov") or {}
chk(abs(float(((pv4.get("chains") or {}).get("exchange:hyperliquid") or {}).get("usd") or 0) - 4000) < 0.02,
    "R4 HL 현금 음수 임시 몫 = 부호 그대로 +4,000(오늘 값·순유입 칸 — 곡선 되감기는 원장 −5,000)", pv4)
chk(abs(sum(float(x["qty"]) for x in (f4.get("stables") or []) if str(x.get("sym")).upper() == "USDC") + 1000) < 1e-6, "R4 화면 USDC = −1,000(지금)",
    [x for x in f4.get("stables") or [] if str(x.get("sym")).upper() == "USDC"])

ctx = flowev._Ctx({7: {"sym": "USDT", "is_stable": True}}, {7: 1.0}, NOW, {"chain": {"eth": "Ethereum"}})
tr5 = [{"state": "prov", "why": "prov", "own": True, "cls": "wallet", "ex": "binance", "uuid": "u5", "gid": 7, "qty": Decimal("30000"), "sym": "USDT",
        "ts": NOW - 3600, "start": NOW - 3600, "addr": W, "net": "ETH", "src": "바이낸스", "dst": "w 지갑", "txid_raw": "0x" + "ab" * 32}]
ev5 = T.safe(flowev.classify, [], ctx, transit=tr5)
arr5 = [(e.get("arr") or {}).get("st") for e in (ev5 if isinstance(ev5, list) else [])]
chk(arr5 == ["none"], "R5 받는 쪽 첫 대사 전(prov) 출금 = 도착 확인 불가(none — '아직 안 들어옴' 오경보 없음)", [arr5, ev5 if not isinstance(ev5, list) else ""])

clk = {"t": 1_800_000_000.0}
CALLS = []


def fake_http(url, body=None, timeout=20):
    t = (body or {}).get("type")
    CALLS.append(t)
    if t == "spotMeta":
        return {"tokens": [{"name": "USDC", "index": 0, "tokenId": "0x" + "00" * 16}, {"name": "HYPE", "index": 150, "tokenId": "0x" + "11" * 16}],
                "universe": [{"name": "HYPE/USDC", "index": 107, "tokens": [150, 0]}]}
    if t == "spotClearinghouseState":
        return {"balances": [{"coin": "USDC", "token": 0, "total": "1000"}, {"coin": "HYPE", "token": 150, "total": "5"}]}
    if t == "userAbstraction":
        return "default"
    if t == "perpDexs":
        return [None] + [{"name": f"dx{i}"} for i in range(60)]
    if t == "clearinghouseState":
        return {"marginSummary": {"accountValue": "0"}, "assetPositions": []}
    if t == "delegatorSummary":
        return {"delegated": "0", "undelegated": "0", "totalPendingWithdrawal": "0"}
    return {}


sv = (hl_spot.HTTP, hl_spot.CLOCK, hl_spot.SLEEP, hl_spot.addresses)
hl_spot.HTTP = fake_http
hl_spot.CLOCK = lambda: clk["t"]
hl_spot.SLEEP = lambda s: clk.__setitem__("t", clk["t"] + max(0.01, float(s)))
hl_spot.addresses = lambda cfg: ["0x" + "4d" * 20]
hl_spot.GOV = hl_spot.Gov()
hl_spot._META.clear()
os.remove(os.path.join(S, "exf_balances_hyperliquid.json.view"))
r6 = T.safe(hl_spot.prefetch_view, {}, poll=600, now=clk["t"])
v6 = statefile.read_json(os.path.join(S, "exf_balances_hyperliquid.json.view"), {}) if os.path.exists(os.path.join(S, "exf_balances_hyperliquid.json.view")) else {}
chk(isinstance(r6, str) and r6.startswith("ok") and (v6.get("balances") or {}).get("USDC") == 1000.0 and "perpDexs" not in CALLS,
    "R6 HL 먼저 읽기 = 현물 주소당 1콜(+ 부가 3) · 퍼프 DEX 60개를 안 훑음 · 마감 안 넘음(Budget 없음)", [r6, v6, CALLS[:8], len(CALLS)])
hl_spot.HTTP, hl_spot.CLOCK, hl_spot.SLEEP, hl_spot.addresses = sv
T.finish()
sys.exit(1 if T.FAILS else 0)
