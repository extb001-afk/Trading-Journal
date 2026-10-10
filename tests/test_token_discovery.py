#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import importlib.util
import json
import os

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W = "0x" + "b1" * 20
W2 = "0x" + "b2" * 20
CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "rpcs": ["https://rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "bsc_rpc", "chain": "bsc", "address": W},
                   {"type": "bsc_rpc", "chain": "bsc", "address": W2}],
       "native_symbol": {"eth": "ETH", "bsc": "BNB"}, "backfill_months": 5, "bsc": {"detail_rpcs": ["https://bscrpc.invalid"]}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import recon
try:
    import token_discovery as td
except ImportError:
    td = None

core.dm = lambda *a, **k: None
chk = T.chk
TA = "0x" + "a1" * 20
TB = "0x" + "a2" * 20
TS = "0x" + "a3" * 20
TZ = "0x" + "a4" * 20
TN = "0x" + "a5" * 20
E18 = 10 ** 18
BAL = {TA: 5 * E18, TB: 7 * E18, TS: 9 * E18, TN: 3 * E18}
CALLS = {"disc": [], "dex": []}


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
        if key[0] == "bal":
            out[key] = BAL.get(ca, 0).to_bytes(32, "big")
        elif key[0] == "dec":
            out[key] = (18).to_bytes(32, "big")
    return out


recon._rpc_any = fake_rpc_any
recon._mc_call = fake_mc
recon._gj = lambda url, timeout=30.0, tries=None, sleep=None: [{"token": {"type": "ERC-20", "address_hash": TA, "symbol": "TKA"}, "value": str(5 * E18)}]
recon.BS_PACE = 0


def fake_discover(chain, wallet, upto=None, cfg=None, env=None, sources=None, sleep=None, deadline=None, **kw):
    CALLS["disc"].append((chain, wallet))
    return {"cas": {TA: ["etherscan"], TB: ["etherscan"], TS: ["etherscan"], TZ: ["etherscan"], TN: ["etherscan"]},
            "meta": {TB: {"sym": "OLDT", "dec": 18}, TS: {"sym": "FREEDROP"}, TZ: {"sym": "ZERO"}, TN: {"sym": "Visit claim-reward.com"}},
            "ok": {s: 1 for s in (sources or ["etherscan"])}, "fail": {}, "calls": {"etherscan": 1}}


def fake_dex(chain, cas, min_reserve=10000.0, sleep=None):
    CALLS["dex"].append(sorted(cas))
    return {ca: ((True, 50000.0, 1.25, "OLDT") if ca == TB else (False, 12.0, None, None)) for ca in cas}


if td is not None:
    td.discover = fake_discover
    td.dex_check = fake_dex
c = core.Core(common.load_config())
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_eth.json"), {W: 900})
c._wallet_backfilled = lambda *a: True
c._recon_quiet = lambda *a: True
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_eth', '1')")
c.conn.commit()


def run_new(mode="new"):
    bal = c._recon_fetch_plan("eth", "evm", [W], mode)()
    c._recon_bal = lambda chain, kind, md, wallets, bal=bal: bal
    n = c._wrecon_run("eth", "evm", "evm", set(), 1780000000, True, mode, [W])
    c.__dict__.pop("_recon_bal", None)
    return bal, n


def opening(ca):
    r = c.conn.execute("SELECT sum(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                       " WHERE p.source_kind='opening' AND a.address=? AND p.location=?", (ca, f"wallet:eth:{W}")).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


bal, n = run_new()
chk(opening(TB) == 7 * E18, "D1 블록스카웃이 안 준 옛 보유 토큰(발견 출처만 앎) = 같은 블록 잔고로 기초 잔고 앵커", opening(TB))
chk(opening(TA) == 5 * E18, "D1 블록스카웃 목록 토큰 = 종전 그대로 앵커", opening(TA))
chk(opening(TS) == 0 and opening(TN) == 0, "D2 발견된 스팸(유동성 없음 · 스캠 이름) = 잔고가 있어도 앵커 안 함", (opening(TS), opening(TN)))
skip = (bal.get("_disc_skip") or {}).get(W) or {}
chk(TS in skip and TN in skip and "유동성" in skip.get(TS, "") and "이름" in skip.get(TN, ""), "D2 스팸 사유 기록(유동성 부족 · 스캠 이름)", skip)
q = set((bal.get("_queried") or {}).get(W) or ())
chk(TB in q and TS not in q and TN not in q, "D2 스팸 칸 = 조회 범위(_q) 밖(관측 아님 — 원장 그대로)", sorted(x[:6] for x in q))
chk(TZ in q and opening(TZ) == 0, "D3 발견으로만 물은 잔고 0 칸 = 관측 0(조회 범위 안 — 늦게 온 그 블록 이전 흐름을 앵커가 흡수) · 앵커 없음", sorted(x[:6] for x in q))
chk(CALLS["dex"] and TN not in CALLS["dex"][0] and TS in CALLS["dex"][0], "D2 덱스스크리너 = 정적으로 모르는 것만(스캠 이름은 정적 판정)", CALLS["dex"])
if td is not None:
    stx = td.load_state()
    chk(TS in ((stx.get("pairs") or {}).get(f"eth:{W}") or {}).get("skip", {}), "D2 상태 파일에 스팸 의심 칸 기록", list(stx.get("pairs") or {}))
pay = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:eth:{W}",)).fetchone()[0])
chk(pay.get(W, {}).get(f"token:{TB}") == 7 * E18 and f"{W}:{TB}" in (pay.get("_q") or []) and f"token:{TS}" not in pay.get(W, {})
    and f"{W}:{TS}" not in (pay.get("_q") or []), "D10 관측 payload = 발견 토큰 칸·조회 범위 포함 · 스팸 칸 없음(rebuild2 가 같은 앵커를 재현)",
    {k: v for k, v in pay.items() if k != W})
n_open = c.conn.execute("SELECT count(*) FROM postings WHERE source_kind='opening'").fetchone()[0]
if td is not None:
    c._recon_new_wallets("eth", "evm", "evm", set(), 1780000000)
n_open2 = c.conn.execute("SELECT count(*) FROM postings WHERE source_kind='opening'").fetchone()[0]
chk(n_open2 == n_open, "D10 같은 지갑 두 번째 = 새 앵커 0(wrecon_done 도장 — 멱등)", (n_open, n_open2))

if td is None:
    T.finish()
    sys.exit(0)

env0 = {}
p0 = td.plan("base", {"chains": {"base": {"rpcs": ["https://rpc.invalid"]}}}, env0)
chk(not ({"alchemy", "ankr", "etherscan"} & set(p0)), "D4 키 없음 = Alchemy·Ankr·이더스캔 출처 없음", p0)
r0 = td.__dict__["src_alchemy"]
try:
    r0("base", W, td.alchemy_url("base", env0), out={}, meta={})
    chk(False, "D4 Alchemy 키 없음 = nokey", "예외 없음")
except td.SourceFail as e:
    chk(e.kind == "nokey", "D4 Alchemy 키 없음 = nokey(호출 0)", e.kind)
chk(td.old_status("base", {"chains": {"base": {}}}, env0) == "nokey" and td.old_status("eth", {"chains": {"eth": {}}}, {"TJ_ETHERSCAN_KEY": "k" * 20}) == "free",
    "D4 옛 보유 상태: Base 키 없음 = nokey · Ethereum 이더스캔 키 = free", (td.old_status("base", {}, env0),))
td_disc_real = importlib.util.spec_from_file_location("td_real", os.path.join(T.SRC, "token_discovery.py"))
tdr = importlib.util.module_from_spec(td_disc_real)
td_disc_real.loader.exec_module(tdr)
rr = tdr.discover("base", W, cfg={"chains": {"base": {}}}, env=env0, sources=["alchemy", "ankr", "etherscan"])
chk(rr["cas"] == {} and set(rr["fail"]) == {"alchemy", "ankr", "etherscan"} and all(v.startswith(("nokey", "unsupported")) for v in rr["fail"].values()),
    "D4 키 없는 출처 = 실패 기록만(호출 0 · 예외 없음)", rr["fail"])

td.update_state(lambda cur: {"v": 1, "pairs": {}})
CALLS["disc"].clear()
prep = td.recon_prep(c.conn, c.cfg, "eth", [W, W2], None)
e1 = td.recon_extra(prep)
chk(len(CALLS["disc"]) == 2 and e1["status"] == {W: "ok", W2: "ok"}, "D5 처음 = (체인, 지갑)마다 1회 전수", (CALLS["disc"], e1["status"]))
prep = td.recon_prep(c.conn, c.cfg, "eth", [W, W2], None)
e2 = td.recon_extra(prep)
chk(len(CALLS["disc"]) == 2 and e2["status"] == {W: "cache", W2: "cache"} and e2["extra"][W] == e1["extra"][W],
    "D5 두 번째 주기 · 신호 그대로 = 발견 0콜(캐시 결과 그대로)", (len(CALLS["disc"]), e2["status"]))
aid9 = c.asset_id("token", "eth", TA, symbol="TKA", decimals=18)
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
               " VALUES ('chain_tx','eth',?,0,1789000000,?,?,'1','acq','TRANSFER_IN',1)", ("0x" + "e1" * 32, aid9, f"wallet:eth:{W2}"))
c.conn.commit()
prep = td.recon_prep(c.conn, c.cfg, "eth", [W, W2], None)
e3 = td.recon_extra(prep)
chk(len(CALLS["disc"]) == 3 and e3["status"] == {W: "cache", W2: "ok"}, "D5 원장에 새 거래가 기장된 지갑만 다시(키 API) · 나머지 0콜", (CALLS["disc"][-1:], e3["status"]))
ent = td.entry("eth", W)
chk(td.need_refresh(ent, {"txn": ent["sig"]["txn"], "txts": ent["sig"]["txts"]})[0] is False
    and td.need_refresh(ent, {"txn": ent["sig"]["txn"] + 1})[1] == "changed:txn", "D5 need_refresh 신호 비교", ent.get("sig"))
chk(td.need_refresh(ent, {}, srcs=["alchemy"])[1] == "new:alchemy", "D5 새로 넣은 키(그때 안 쓴 출처) = 그 쌍 1회 다시", td.need_refresh(ent, {}, srcs=["alchemy"]))

import bf_engine
old_b = bf_engine.ES_DAILY_BUDGET
bf_engine.ES_DAILY_BUDGET = 0
n_net = len(T.NET_TRIES)
try:
    tdr.src_etherscan("eth", W, env={"TJ_ETHERSCAN_KEY": "k" * 20}, out={}, meta={})
    chk(False, "D6 이더스캔 예산 0 = 거절", "예외 없음")
except tdr.SourceFail as e:
    chk(e.kind == "quota" and len(T.NET_TRIES) == n_net, "D6 이더스캔 하루 예산(80% 장부) 다 씀 = 0콜 거절(quota)", (e.kind, T.NET_TRIES[n_net:]))
bf_engine.ES_DAILY_BUDGET = old_b
bf_engine.rpc_day_configure({"rpc_day_limits": {"node_alchemy": {"hosts": ["*.g.alchemy.com"], "unit": "cu", "day": 20, "pct": 80,
                                                                  "cu": 26, "cu_methods": {"alchemy_getTokenBalances": 20}}}})
bf_engine._CONFIGURED[0] = True
try:
    tdr.src_alchemy("eth", W, "https://eth-mainnet.g.alchemy.com/v2/" + "k" * 20, out={}, meta={})
    chk(False, "D6 Alchemy 몫 없음 = 거절", "예외 없음")
except tdr.SourceFail as e:
    chk(e.kind == "quota" and not any("alchemy" in h for h in T.NET_TRIES[n_net:]),
        "D6 Alchemy 노드 하루 장부(80%) 몫 없음 = 0콜 거절(quota)", (e.kind, str(e)[:80], T.NET_TRIES[n_net:]))

TX = "0x" + "c1" * 20
TO = "0x" + "c2" * 20
for ca, sym in ((TX, "FAKE"), (TO, "OWNT")):
    c.conn.execute("INSERT INTO assets (kind, chain, address, symbol, decimals, confirmed) VALUES ('token','bsc',?,?,18,0)", (ca, sym))
aidx = c.conn.execute("SELECT asset_id FROM assets WHERE chain='bsc' AND address=?", (TX,)).fetchone()[0]
aido = c.conn.execute("SELECT asset_id FROM assets WHERE chain='bsc' AND address=?", (TO,)).fetchone()[0]
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
               " VALUES ('chain_tx','bsc',?,0,1789000000,?,?,'1','acq','TRANSFER_IN',1)", ("0x" + "e2" * 32, aidx, f"wallet:bsc:{W2}"))
c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
               " VALUES ('chain_tx','bsc',?,0,1789000000,?,?,'1','acq','TRANSFER_IN',1)", ("0x" + "e3" * 32, aido, f"wallet:bsc:{W}"))
c.conn.commit()
seen_b = []


def fake_bsc(rpcs, wallets, cas):
    seen_b.append((list(wallets), sorted(cas)))
    w = wallets[0]
    per = {("native", None): 0}
    zero = []
    for ca in cas:
        v = 4 * E18 if ca in (TX, TO) else 0
        if v:
            per[("token", ca)] = v
        else:
            zero.append(ca)
    return {"per_wallet": {w: per}, "_meta": {ca: cas[ca] for ca in cas}, "_zero": {w: zero}}


recon.fetch_bsc_balances = fake_bsc
td.discover = lambda *a, **k: {"cas": {}, "meta": {}, "ok": {"rabby": 0}, "fail": {}, "calls": {}}
td.update_state(lambda cur: {"v": 1, "pairs": {}})
bb = c._recon_fetch_plan("bsc", "bsc", [W])()
chk(seen_b and TX in seen_b[0][1] and TO in seen_b[0][1], "D7 색인 발견 없음 = 종전처럼 원장 BSC 토큰 전체를 물음", seen_b)
pw = (bb.get("per_wallet") or {}).get(W) or {}
chk(("token", TO) in pw and ("token", TX) not in pw, "D7 그 지갑 원장 토큰 = 그대로 · 다른 지갑 원장에만 있는(유동성 없는) 토큰 = 앵커 안 함", sorted(k[1][:6] for k in pw if k[0] == "token"))
chk(TX in ((bb.get("_disc_skip") or {}).get(W) or {}), "D7 차단 사유 기록", bb.get("_disc_skip"))
td.discover = lambda *a, **k: {"cas": {TB: ["alchemy"]}, "meta": {TB: {"sym": "OLDT", "dec": 18}}, "ok": {"alchemy": 1}, "fail": {}, "calls": {"alchemy": 1}}
td.update_state(lambda cur: {"v": 1, "pairs": {}})
seen_b.clear()
c._recon_fetch_plan("bsc", "bsc", [W])()
chk(seen_b and TX not in seen_b[0][1] and TO in seen_b[0][1] and TB in seen_b[0][1],
    "D7 색인 발견이 되면 = 그 지갑 원장 ∪ 발견 ∪ 원장 정품만(스팸 대량 질문 줄임)", seen_b)

import balcheck
TD8 = "0x" + "d1" * 20
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {"at": 1, "sig": {"txn": 0, "txts": 0}, "cas": {TD8: ["ankr"]},
                                                            "meta": {TD8: {"sym": "DISC", "dec": 18, "wl": True, "px": 2.0}},
                                                            "ok": {"ankr": 1, "blockscout": 0, "rabby": 0}, "fail": {}}}})
rpc_log = []


def fake_rpc(u, method, params, timeout=25.0, gap=True):
    rpc_log.append(method)
    if method == "eth_getBalance":
        return "0x0"
    if method == "eth_call":
        to = params[0]["to"].lower()
        return hex(1000 * E18) if to == TD8 else "0x0"
    raise AssertionError(method)


recon._rpc = fake_rpc
balcheck.time.sleep = lambda s: None
d_calls = []
td.discover = lambda *a, **k: d_calls.append(a) or {"cas": {}, "meta": {}, "ok": {x: 0 for x in (k.get("sources") or [])}, "fail": {}, "calls": {}}
cfg8 = dict(common.load_config(), backfill_months=0)
cfg8["wallets"] = [{"type": "evm", "chain": "eth", "address": W}]
st8 = balcheck.run_once(cfg8, c.conn, {}, set(), {})
mm = [m for m in st8.get("mismatches") or [] if m.get("ca") == TD8]
chk(mm and mm[0]["onchain"] == 1000.0 and mm[0]["ledger"] == 0.0 and mm[0]["diffUsd"] == 2000.0,
    "D8 발견 캐시의 원장 밖 보유(값 앎) = 잔고 불일치로 드러남", mm or st8.get("errors"))
chk(not d_calls, "D8 신호 기준이 없던 쌍 = 기준만 적음(발견 다시 0콜)", d_calls)
st8b = balcheck.run_once(cfg8, c.conn, {}, set(), st8)
chk(not d_calls and isinstance(st8b.get("disc"), dict), "D8 두 번째 판 · 신호 그대로 = 발견 0콜 · 상태에 발견 요약", (d_calls, st8b.get("disc")))
fake_rpc_nat = fake_rpc


def fake_rpc2(u, method, params, timeout=25.0, gap=True):
    return "0x5" if method == "eth_getBalance" else fake_rpc_nat(u, method, params, timeout, gap)


recon._rpc = fake_rpc2
balcheck.run_once(cfg8, c.conn, {}, set(), st8b)
chk(len(d_calls) == 1, "D8 네이티브 잔고 바뀜(무료 신호) = 그 쌍만 발견 다시(1회)", len(d_calls))

import coverage_limits
t9 = coverage_limits.api_limits_table(T.ROOT)
rows9 = {c9["id"]: c9["rows"] for c9 in (t9 or {}).get("chains") or []}
ob = [r for r in rows9.get("base", []) if r.get("kind", "").startswith("옛 보유")]
chk(ob and "확인 불가" in ob[0]["miss"], "D9 Base 묶음 '옛 보유 토큰 찾기' 줄 — 키 없으면 확인 불가 명시", ob)
ob2 = [r for r in rows9.get("evm_explorer", []) if r.get("kind", "").startswith("옛 보유")]
chk(ob2 and ob2[0]["miss"] == "없음" and "이더스캔" in ob2[0]["api"], "D9 Ethereum 등 = 무료 색인 · 못 받는 것 없음", ob2)
sm = td.summary({"wallets": [{"type": "evm", "chain": "base", "address": W}, {"type": "evm", "chain": "eth", "address": W}],
                 "chains": {"base": {}, "eth": {}}}, env={})
chk("base" in sm["noOld"] and "eth" not in sm["noOld"], "D9 상태 요약 = 옛 보유 확인 불가 체인(키 없음) 목록", sm)

spec = importlib.util.spec_from_file_location("token_recheck", os.path.join(T.ROOT, "tools", "token_recheck_1010.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)
TC = "0x" + "f1" * 20
aidc = c.asset_id("token", "eth", TC, symbol="LT", decimals=18)
for i9, (blk9, q9) in enumerate(((800, 2 * E18), (950, 5 * E18))):
    h9 = "0x" + ("%02x" % (0xa0 + i9)) * 32
    c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
                   " VALUES ('chain_tx','eth',?,0,1789000000,?,?,?,'acq','TRANSFER_IN',1)", (h9, aidc, f"wallet:eth:{W2}", str(q9)))
c.conn.commit()
cols = [r[1] for r in c.conn.execute("PRAGMA table_info(raw_txs)")]
for h9, blk9 in (("0x" + "a0" * 32, 800), ("0x" + "a1" * 32, 950), ("0x" + "e1" * 32, 850)):
    v9 = {k: ("{}" if k in ("payload", "raw", "snapshot") else 1) for k in cols}
    v9.update(chain="eth", txhash=h9, block=blk9)
    c.conn.execute(f"INSERT OR REPLACE INTO raw_txs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [v9[k] for k in cols])
c.conn.commit()
sums, _m, unk = tr.ledger_at(c.conn, "eth", W2, 900)
chk(sums.get(TC) == 2 * E18 and unk == 0, "D11 원장 합 = 그 블록 이하 기장만(core._posted_sums_at 기준)", (sums.get(TC), unk))
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_eth.json"), {W: 900, W2: 900})
recon._rpc_any = fake_rpc_any
recon._mc_call = fake_mc
BAL[TC] = 3 * E18
td.discover = lambda chain, wallet, **k: {"cas": {TB: ["etherscan"], TS: ["etherscan"]}, "meta": {TB: {"sym": "OLDT", "dec": 18}, TS: {"sym": "FREEDROP"}},
                                          "ok": {"etherscan": 2}, "fail": {}, "calls": {"etherscan": 1}}
td.dex_check = fake_dex


class _A:
    use_cache = False
    logs_max_calls = 10


res = tr.run_pair(common, td, recon, c.cfg, c.conn, "eth", W2, _A(), {}, {})
rows = {r["ca"]: r for r in res["rows"]}
KEYS = {"chain", "wallet", "ca", "symbol", "decimals", "block", "chain_bal_raw", "ledger_raw", "diff_raw", "spam", "sources"}
chk(rows and all(set(r) == KEYS for r in rows.values()), "D11 JSON 줄 형식 = 약속한 키 그대로", [sorted(r) for r in rows.values()][:1])
chk(rows.get(TB, {}).get("diff_raw") == 7 * E18 and rows[TB]["spam"] is False and "etherscan" in rows[TB]["sources"],
    "D11 옛 보유(원장 0 · 체인 7) = 차이 7 · 스팸 아님 · 출처", rows.get(TB))
chk(rows.get(TS, {}).get("spam") is True, "D11 유동성 없는 발견 토큰 = 스팸 표시", rows.get(TS))
chk(rows.get(TC, {}).get("ledger_raw") == 2 * E18 and rows[TC]["chain_bal_raw"] == 3 * E18 and rows[TC]["diff_raw"] == E18
    and "ledger_wallet" in rows[TC]["sources"], "D11 원장 토큰 = 블록 900 이하 합(2)과 체인(3) 비교", rows.get(TC))
res2 = tr.run_pair(common, td, recon, c.cfg, c.conn, "eth", W2, _A(), {}, {}, explain_on=True)
chk("onc_all" in res2["usd"] and res2["usd"]["diff_cred"] > 0 and res2["usd"]["diff_spam"] == 0,
    "D11 설명 지갑 = 체인 실잔고 평가 · 토큰 차이 달러(믿을 만한 것만 · 스팸 값 없음)", res2["usd"])
json.dump({"wallets": {W2: {"total": 900.0, "chains": [{"id": "eth", "cid": 1, "usd": 800.0}, {"id": "xyzchain", "cid": 999999, "usd": 100.0}],
                            "tokens": [], "protocols": [{"proto": "p1", "pname": "합성 스테이킹", "chain": "eth",
                                                         "items": [{"a": 300.0, "d": 0.0, "assets": [], "debts": []}]}]}}},
          open(os.path.join(common.STATE_DIR, "rabby_portfolio.json"), "w"))
ex = "\n".join(tr.explain(common, c.cfg, {("eth", W2): res2}, [W2]))
chk("프로토콜·스테이킹 $300" in ex and "지갑 토큰 $500" in ex and "토큰으로 설명되는 몫" in ex and "봇 미추적 체인" in ex,
    "D11 Rabby 설명 = 프로토콜·스테이킹 몫(토큰 아님) / 토큰으로 설명되는 몫 / 봇 미추적 체인 따로", ex)
n_net = len(T.NET_TRIES)
rc = tr.main(["--plan-only", "--quiet"])
chk(rc == 0 and len(T.NET_TRIES) == n_net, "D11 --plan-only = 예상만(바깥 연결 0)", (rc, T.NET_TRIES[n_net:]))

PR = {"chain": "eth", "strict": None, "confirmed": set(), "min_reserve": 10000.0}
X1, X2, X3 = "0x" + "71" * 20, "0x" + "72" * 20, "0x" + "73" * 20


def fbal(cas, meta=None):
    return {"per_wallet": {W: {("token", ca): 5 * E18 for ca in cas}}, "_extra_only": {W: list(cas)}, "_queried": {W: list(cas)},
            "_meta": dict(meta or {})}


b12 = td.filter_result(fbal([X1, X2]), PR, {"meta": {}, "src": {W: {X1: ["alchemy"], X2: ["alchemy"]}}, "status": {}},
                       dex=lambda ch, cas, mr=0: {X1: (True, 5e4, 1.0, "Visit claim-x.com"), X2: (True, 5e4, 1.0, None)})
pw12 = b12["per_wallet"][W]
sk12 = (b12.get("_disc_skip") or {}).get(W) or {}
chk(("token", X1) not in pw12 and "유도" in sk12.get(X1, ""), "D12 Alchemy 단독 후보 · 덱스 심볼이 링크 유도 이름 = 앵커 안 함(#1)", sk12)
chk(("token", X2) not in pw12 and "심볼 모름" in sk12.get(X2, ""), "D12 심볼을 어디서도 모름 = 앵커 안 함(#1)", sk12)
b12b = td.filter_result(fbal([X3], {X3: ("USDT", 6)}), PR, {"meta": {X3: {"wl": True}}, "src": {W: {X3: ["ankr"]}}, "status": {}},
                        dex=lambda ch, cas, mr=0: {})
chk(("token", X3) not in b12b["per_wallet"][W], "D12 조회 결과 심볼(원장·BSC 폴백) 대표 심볼 흉내 = 믿음 출처가 있어도 앵커 안 함(#1)",
    (b12b.get("_disc_skip"), b12b["per_wallet"][W]))

B1, B2 = "0x" + "81" * 20, "0x" + "82" * 20


def fake_bsc2(rpcs, wallets, cas):
    return {"per_wallet": {wallets[0]: {("native", None): 0, ("token", B1): 3 * 10 ** 6, ("token", B2): 4}},
            "_meta": {ca: cas[ca] for ca in cas}, "_zero": {wallets[0]: []}}


def fake_rpc_dec(urls, method, params, check=None, tries=None, sleep=None, timeout=25.0):
    if method == "eth_call" and params[0]["to"] == B1:
        return "0x" + "6".rjust(64, "0")
    raise recon.RpcExecFail("rpc eth_call: 실행 오류 — execution reverted")


recon._rpc_any = fake_rpc_dec
ext13 = {"extra": {W: {B1, B2}}, "meta": {B1: {"sym": "BONE", "wl": True}, B2: {"sym": "BTWO", "wl": True}}, "src": {W: {B1: ["ankr"], B2: ["ankr"]}},
         "status": {W: "ok"}, "fail": {}, "ok": {W: {"ankr": 2}}}
_rx = td.recon_extra_safe
td.recon_extra_safe = lambda prep, upto=None, **k: ext13
b13 = td.bsc_fetch(["https://bscrpc.invalid"], [W], {}, {W: set()}, dict(PR, chain="bsc"), fetch=fake_bsc2)
td.recon_extra_safe = _rx
chk(b13["_meta"].get(B1) == ("BONE", 6) and ("token", B1) in b13["per_wallet"][W], "D13 BSC 발견 토큰 소수 = 같은 decimals() 조회값 6(#2)", b13["_meta"].get(B1))
chk(("token", B2) not in b13["per_wallet"][W] and "소수" in ((b13.get("_disc_skip") or {}).get(W) or {}).get(B2, ""),
    "D13 decimals() 못 읽음 = 그 칸 앵커 안 함(#2)", b13.get("_disc_skip"))
recon._rpc_any = fake_rpc_any

X4 = "0x" + "74" * 20
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {"at": int(__import__("time").time()), "sig": {}, "cas": {X4: ["alchemy"]},
                                                            "meta": {X4: {"alnz": False}}, "ok": {"alchemy": 1, "blockscout": 0, "rabby": 0}, "fail": {}}}})
e14 = td.recon_extra(td.recon_prep(c.conn, c.cfg, "eth", [W], None))
chk(X4 in (e14["extra"].get(W) or set()), "D14 Alchemy 현재 잔고 0 후보도 커서 블록 balanceOf 대상(#3)", sorted(x[:6] for x in e14["extra"].get(W) or ()))

ent16 = {"at": 1, "sig": {}, "ok": {}, "fail": {"alchemy": "http: 429"}}
chk(td.need_refresh(ent16, {}) == (True, "retry"), "D16 HTTP 실패 출처 = RETRY_FAIL_SEC 뒤 다시(#5)", td.need_refresh(ent16, {}))
chk(td.need_refresh({"at": 1, "sig": {}, "ok": {}, "fail": {"alchemy": "unsupported: x"}}, {})[0] is False, "D16 종결 실패(지원 안 함) = 다시 안 함", "")

KEY17 = "Zx" + "9" * 30
_sa = tdr.src_alchemy
tdr.src_alchemy = lambda *a, **k: (_ for _ in ()).throw(tdr.SourceFail("error", "upstream said key " + KEY17 + " invalid"))
r17 = tdr.discover("eth", W, cfg={"chains": {"eth": {}}}, env={"TJ_ALCHEMY_KEY": KEY17}, sources=["alchemy"])
tdr.src_alchemy = _sa
chk(KEY17 not in json.dumps(r17["fail"]) and "alchemy" in r17["fail"], "D17 JSON-RPC 오류 원문 속 키 = 저장 전 가림(#6)", r17["fail"])


def _d18():
    bf_engine.rpc_day_configure({"rpc_day_limits": {"node_ankr": {"hosts": ["rpc.ankr.com"], "unit": "cu", "month": 200000000, "pct": 80, "cu": 200}}})
    tdr._ensure_ledger("rpc.ankr.com", method_cu=("ankr_getAccountBalance", 700))
    chk(bf_engine._rpc_day_units("node_ankr", ["ankr_getAccountBalance"]) == 700, "D18 Ankr getAccountBalance 예약 = 700 크레딧(#7)",
        bf_engine._rpc_day_units("node_ankr", ["ankr_getAccountBalance"]))
    bf_engine.rpc_day_configure({"rpc_day_limits": {"node_ankr": {"hosts": ["rpc.ankr.com"], "unit": "cu", "month": 200000000, "pct": 80, "cu": 200,
                                                                  "cu_methods": {"ankr_getAccountBalance": 650}}}})
    tdr._ensure_ledger("rpc.ankr.com", method_cu=("ankr_getAccountBalance", 700))
    chk(bf_engine._rpc_day_units("node_ankr", ["ankr_getAccountBalance"]) == 650, "D18 장부 표에 단가가 이미 있으면 그대로(이중 계상 없음)",
        bf_engine._rpc_day_units("node_ankr", ["ankr_getAccountBalance"]))


TOKS = ["0x" + ("%02x" % (0x90 + i)) * 20 for i in range(10)]
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {"at": 1, "sig": {"txn": 0, "txts": 0, "nat": "5"}, "cas": {t: ["ankr"] for t in TOKS},
                                                            "meta": {t: {"sym": "DT%d" % i, "dec": 18, "wl": True, "px": 2.0} for i, t in enumerate(TOKS)},
                                                            "ok": {"ankr": 10, "blockscout": 0, "rabby": 0}, "fail": {}}}})
seen15 = []


def fake_rpc15(u, method, params, timeout=25.0, gap=True):
    if method == "eth_getBalance":
        return "0x5"
    if method == "eth_call":
        seen15.append(params[0]["to"].lower())
        return hex(1000 * E18) if params[0]["to"].lower() in TOKS else "0x0"
    raise AssertionError(method)


recon._rpc = fake_rpc15
td.discover = lambda *a, **k: {"cas": {}, "meta": {}, "ok": {x: 0 for x in (k.get("sources") or [])}, "fail": {}, "calls": {}}
s15a = balcheck.run_once(cfg8, c.conn, {}, set(), {})
r1 = {t for t in seen15 if t in TOKS}
seen15.clear()
s15b = balcheck.run_once(cfg8, c.conn, {}, set(), s15a)
r2 = {t for t in seen15 if t in TOKS}
chk(len(r1) == 8 and r1 | r2 == set(TOKS) and r1 != r2, "D15 발견 후보 순환 — 두 판에 10개 전부(#4)", (len(r1), len(r2), len(r1 | r2)))
k15 = {m["key"] for m in s15b.get("mismatches") or []}
chk(all(f"eth:{W}:{t}" in k15 for t in TOKS), "D15 이번 판 못 본 후보의 지난 불일치 = 이월로 유지(#4)", len(k15))

seen15.clear()
s19 = balcheck.run_once(dict(cfg8, token_discovery={"enabled": False}), c.conn, {}, set(), {})
chk(not any(t in TOKS for t in seen15) and "disc" not in s19, "D19 token_discovery.enabled=false = 잔고 대조 발견 대조·재발견 없음(#8)", (len(seen15), list(s19)[:3]))


def _d20():
    PRG = os.path.join(T.TMP, "prog20.json")
    seq20 = []


    def fake_pair(common_, td_, recon_, cfg_, conn_, chain, w, a, env, dex_cache, explain_on=False):
        seq20.append((chain, w))
        bad = (chain, w) == ("eth", W)
        return {"chain": chain, "wallet": w, "block": 900, "rows": [], "table": [], "native": None, "usd": {}, "stop": None, "err": None,
                "disc": {"ok": {}, "fail": ({"alchemy": "http: 503"} if bad else {"ankr": "unsupported: x"}), "calls": {}, "cache": False}}


    _rp = tr.run_pair
    tr.run_pair = fake_pair
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_bsc.json"), {"head": 900})
    tr.main(["--quiet", "--go", "--progress", PRG, "--out", os.path.join(T.TMP, "o20.jsonl")])
    pg = common.read_json(PRG, {})
    chk(f"eth:{W}" not in (pg.get("done") or {}) and f"eth:{W}" in (pg.get("retry") or {}) and f"bsc:{W}" in (pg.get("done") or {}),
        "D20 출처 실패(HTTP 503) 쌍 = done 아님 · retry 사유 · 종결 실패만인 쌍 = done(#9)", (sorted(pg.get("done") or {}), pg.get("retry")))
    seq20.clear()
    tr.main(["--quiet", "--go", "--only-failed", "--progress", PRG, "--out", os.path.join(T.TMP, "o20.jsonl")])
    chk(seq20 == [("eth", W)], "D20 --only-failed = 실패 쌍만 다시", seq20)
    common.atomic_write_json(PRG, {"done": {f"bsc:{W}": 1, f"eth:{W}": 1}, "res": {f"eth:{W}": {"err": "잔고 조회 실패: x"}, f"bsc:{W}": {}}})
    chk(tr.done_keys(common.read_json(PRG, {})) == {f"bsc:{W}"}, "D20 옛 진행 파일 — done 인데 오류 표시 = 다시 할 쌍(호환)", tr.done_keys(common.read_json(PRG, {})))
    tr.run_pair = _rp


def _d21():
    import contextlib
    used21 = []


    @contextlib.contextmanager
    def _lb():
        used21.append(1)
        yield


    bf_engine.ledger_burst = _lb
    tdr.discover("eth", W, cfg={"chains": {"eth": {}}}, env={}, sources=["rabby"], burst=True)
    tdr.discover("eth", W, cfg={"chains": {"eth": {}}}, env={}, sources=["rabby"], burst=False)
    chk(used21 == [1], "D21 burst=True 만 ledger_burst 안에서(최초 전수)", used21)
    del bf_engine.ledger_burst

B3 = "0x" + "83" * 20
W3 = "0x" + "b3" * 20


BO = "0x" + "84" * 20


def fake_bsc3(rpcs, wallets, cas):
    pw = {("native", None): 0, ("token", B3): 2 * 10 ** 6}
    if BO in cas:
        pw[("token", BO)] = 5 * E18
    return {"per_wallet": {wallets[0]: pw}, "_meta": {ca: cas[ca] for ca in cas}, "_zero": {wallets[0]: []}}


calls23 = []


def rpc_transient(urls, method, params, check=None, tries=None, sleep=None, timeout=25.0):
    calls23.append(params[0]["to"])
    raise RuntimeError("rpc eth_call: 전 엔드포인트 실패 — 429")


ext23 = {"extra": {W: {B3}, W3: {B3}}, "meta": {B3: {"sym": "BTHR", "wl": True}}, "src": {W: {B3: ["ankr"]}, W3: {B3: ["ankr"]}},
         "status": {W: "ok", W3: "ok"}, "fail": {}, "ok": {W: {"ankr": 1}, W3: {"ankr": 1}}}
_rx2 = td.recon_extra_safe
td.recon_extra_safe = lambda prep, upto=None, **k: ext23
td.update_state(lambda cur: {"v": 1, "pairs": {}})
recon._rpc_any = rpc_transient
b23 = td.bsc_fetch(["https://bscrpc.invalid"], [W], {BO: ("OWNB", 18)}, {W: {BO}}, dict(PR, chain="bsc"), fetch=fake_bsc3)
skip23 = ((td.load_state().get("pairs") or {}).get(f"bsc:{W}") or {}).get("skip") or {}
pw23 = b23["per_wallet"].get(W) or {}
chk(not (b23.get("_hold") or {}).get(W) and ("token", BO) in pw23 and ("token", B3) not in pw23 and str(skip23.get(B3, "")).startswith("일시 보류"),
    "D22 BSC 소수 조회 일시 실패 = 그 토큰만 이번 대사에서 뺌('일시 보류') · 지갑 보류 없음 · 나머지 칸 앵커(dc447)", (b23.get("_hold"), skip23, sorted(pw23)))


def rpc_dec_once(urls, method, params, check=None, tries=None, sleep=None, timeout=25.0):
    calls23.append(params[0]["to"])
    if len(calls23) == 1:
        return "0x" + "6".rjust(64, "0")
    raise RuntimeError("rpc eth_call: 전 엔드포인트 실패 — 429")


calls23.clear()
recon._rpc_any = rpc_dec_once
b24 = td.bsc_fetch(["https://bscrpc.invalid"], [W, W3], {}, {W: set(), W3: set()}, dict(PR, chain="bsc"), fetch=fake_bsc3)
chk(b24["_meta"].get(B3) == ("BTHR", 6) and ("token", B3) in (b24["per_wallet"].get(W) or {}) and ("token", B3) in (b24["per_wallet"].get(W3) or {})
    and len(calls23) == 1, "D23 같은 새 토큰 두 지갑 — 앞에서 확인한 소수 6 재사용(다시 안 물음 · None 으로 안 덮음)(dc445 #2)", (b24["_meta"].get(B3), len(calls23)))
calls23.clear()
recon._rpc_any = rpc_transient
b27 = td.bsc_fetch(["https://bscrpc.invalid"], [W3], {}, {W3: set()}, dict(PR, chain="bsc"), fetch=fake_bsc3)
chk(b27["_meta"].get(B3) == ("BTHR", 6) and ("token", B3) in (b27["per_wallet"].get(W3) or {}) and not calls23
    and ((td.load_state().get("dec") or {}).get("bsc") or {}).get(B3) == 6,
    "D27 확인된 BSC 소수 = 상태 파일 캐시 — 다음 주기(노드 장애 중)에도 재사용 · decimals() 0콜(dc447 ②)", (b27["_meta"].get(B3), len(calls23)))
td.recon_extra_safe = _rx2
recon._rpc_any = fake_rpc_any
X5 = "0x" + "75" * 20
b25 = td.filter_result(fbal([X1, X5]), PR, {"meta": {X1: {"sym": "PLAIN"}, X5: {"sym": "GOODT", "wl": True}},
                                            "src": {W: {X1: ["etherscan"], X5: ["ankr"]}}, "status": {}}, dex=lambda ch, cas, mr=0: {})
sk25 = (b25.get("_disc_skip") or {}).get(W) or {}
chk(not (b25.get("_hold") or {}).get(W) and ("token", X5) in b25["per_wallet"][W] and ("token", X1) not in b25["per_wallet"][W]
    and str(sk25.get(X1, "")).startswith("일시 보류") and X1 not in ((b25.get("_queried") or {}).get(W) or []),
    "D24 덱스스크리너 장애 = 그 토큰만 미관측('일시 보류') · 지갑 보류 없음 · 믿을 만한 나머지는 앵커(dc447)", (b25.get("_hold"), sk25))
X6, X7 = "0x" + "76" * 20, "0x" + "77" * 20
dex26 = []
b26 = td.filter_result(fbal([X6, X7]), dict(PR, chain="zzchain", strict=lambda ca: ca == X7),
                       {"meta": {X6: {"sym": "PLAINSIX"}}, "src": {W: {X6: ["etherscan"], X7: ["etherscan"]}}, "status": {}},
                       dex=lambda ch, cas, mr=0: dex26.append(cas) or {})
sk26 = (b26.get("_disc_skip") or {}).get(W) or {}
chk(not (b26.get("_hold") or {}).get(W) and ("token", X7) in b26["per_wallet"][W] and ("token", X6) not in b26["per_wallet"][W]
    and "판정 불가" in sk26.get(X6, "") and td.skip_final(sk26.get(X6, "")) and not dex26,
    "D26 덱스 판정 미지원 체인 = 대사 완료(지갑 보류 없음) · 정품만 앵커 · 나머지 최종 skip(일시 아님)(dc447)", (b26.get("_hold"), sk26, dex26))
_sf = getattr(td, "skip_final", None)
chk(callable(_sf) and _sf("유동성 부족 — 스팸 의심") and not _sf("일시 보류 — 판정 출처 장애"), "D24 skip 결정성 판정", "")

TK = ["0x" + ("%02x" % (0xd0 + i)) * 20 for i in range(4)]
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {"at": 1, "sig": {"txn": 0, "txts": 0, "nat": "5"}, "cas": {t: ["ankr"] for t in TK},
                                                            "meta": {t: {"sym": "K%d" % i, "dec": 18, "wl": True, "px": 2.0} for i, t in enumerate(TK)},
                                                            "skip": {TK[0]: "일시 보류 — 판정 출처 장애", TK[1]: "유동성 부족 — 스팸 의심"},
                                                            "ok": {"ankr": 4, "blockscout": 0, "rabby": 0}, "fail": {}}}})
seen25 = []


def fake_rpc25(u, method, params, timeout=25.0, gap=True):
    if method == "eth_getBalance":
        return "0x5"
    seen25.append(params[0]["to"].lower())
    return hex(1000 * E18) if params[0]["to"].lower() in TK else "0x0"


recon._rpc = fake_rpc25
td.discover = lambda *a, **k: {"cas": {}, "meta": {}, "ok": {x: 0 for x in (k.get("sources") or [])}, "fail": {}, "calls": {}}
s25 = balcheck.run_once(cfg8, c.conn, {}, set(), {})
chk(TK[0] in seen25 and TK[1] not in seen25, "D25 일시 사유('일시 보류') skip = 계속 대조 · 결정적 사유(유동성 부족) = 제외(dc445 #1)",
    [t[:6] for t in seen25 if t in TK])
n_stable = len([1 for _ in (__import__("pricing").STABLE_CAS.get("eth") or {})])
cfg25 = dict(cfg8, balance_check={"max_calls": 1 + n_stable + 1})
seen25.clear()
s25b = balcheck.run_once(cfg25, c.conn, {}, set(), {})
done25 = [t for t in seen25 if t in TK]
rr25 = (s25b.get("discRr") or {}).get(f"eth:{W}")
chk(len(done25) == 1 and rr25 == 1, "D25 호출 상한 도중 = 커서는 실제로 조회한 1개만큼(남은 후보는 다음 판 먼저)(dc445 #3)", (len(done25), rr25))

import pricing as _pricing
USDC_E = sorted(_pricing.STABLE_CAS.get("eth") or {})[0].lower()
TK2 = ["0x" + ("%02x" % (0xe0 + i)) * 20 for i in range(2)]
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {"at": 1, "sig": {"txn": 0, "txts": 0, "nat": "5"},
                                                            "cas": {t: ["ankr"] for t in TK2 + [USDC_E]},
                                                            "meta": dict({t: {"sym": "Q%d" % i, "dec": 18, "wl": True, "px": 2.0} for i, t in enumerate(TK2)},
                                                                         **{USDC_E: {"sym": "USDC", "dec": 6, "wl": True, "px": 1.0}}),
                                                            "ok": {"ankr": 3, "blockscout": 0, "rabby": 0}, "fail": {}}}})
seen25.clear()
s28 = balcheck.run_once(cfg8, c.conn, {}, set(), {})
chk(seen25.count(USDC_E) == 1 and (s28.get("discRr") or {}).get(f"eth:{W}") == 0 and all(t in seen25 for t in TK2),
    "D28 원장 밖 스테이블 = 발견 후보와 중복 조회 없음 · 커서 = 발견 후보 2개만 집계(dc447 ③)", (seen25.count(USDC_E), (s28.get("discRr") or {}).get(f"eth:{W}")))


def _try(fn, label):
    try:
        fn()
    except (Exception, SystemExit) as e:
        chk(False, label + " — 실행 실패", repr(e)[:160])


_try(_d18, "D18 Ankr 단가(#7)")
_try(_d20, "D20 점검 도구 진행 파일(#9)")
_try(_d21, "D21 최초 전수 버스트")
c.conn.close()
T.finish()
