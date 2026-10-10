#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
W = "0x" + "c1" * 20
CFG = {"chains": {"eth": {"blockscout": "https://bs.invalid", "rpcs": ["https://rpc.invalid"]}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W}, {"type": "bsc_rpc", "chain": "bsc", "address": W}],
       "native_symbol": {"eth": "ETH", "bsc": "BNB"}, "backfill_months": 5, "bsc": {"detail_rpcs": ["https://bscrpc.invalid"]}}
json.dump(CFG, open(os.path.join(T.TMP, "config.json"), "w"))
import common
import core
import recon
import token_discovery as td

core.dm = lambda *a, **k: None
chk = T.chk
E18 = 10 ** 18
NOW = int(time.time())


def _try(fn, label):
    try:
        fn()
    except (Exception, SystemExit) as e:
        chk(False, label + " — 실행 실패", repr(e)[:200])


XL = "0x" + "d1" * 20
XS = "0x" + "d2" * 20
XN = "0x" + "d3" * 20
XE = "0x" + "d4" * 20
BAL = {XL: 4 * E18, XS: 9000 * E18, XN: 7 * E18, XE: 2 * E18}
DEX = []


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


def fake_dex(chain, cas, min_reserve=10000.0, sleep=None):
    DEX.append(sorted(cas))
    return {ca: ((True, 80000.0, 1.5, "GOODL") if ca == XL else (True, 60000.0, 2.0, "EXT") if ca == XE else (False, 3.0, None, None)) for ca in cas}


recon._rpc_any = fake_rpc_any
recon._mc_call = fake_mc
recon._gj = lambda url, timeout=30.0, tries=None, sleep=None: [
    {"token": {"type": "ERC-20", "address_hash": XL, "symbol": "GOODL"}, "value": str(BAL[XL])},
    {"token": {"type": "ERC-20", "address_hash": XS, "symbol": "FREEAIR"}, "value": str(BAL[XS])},
    {"token": {"type": "ERC-20", "address_hash": XN, "symbol": "Visit claim-reward.com"}, "value": str(BAL[XN])}]
recon.BS_PACE = 0
td.discover = lambda chain, wallet, upto=None, cfg=None, env=None, sources=None, sleep=None, deadline=None, **kw: {
    "cas": {XE: ["etherscan"]}, "meta": {XE: {"sym": "EXT", "dec": 18}}, "ok": {s: 1 for s in (sources or ["etherscan"])}, "fail": {}, "calls": {}}
td.dex_check = fake_dex

c = core.Core(common.load_config())
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_eth.json"), {W: 900})
c._wallet_backfilled = lambda *a: True
c._recon_quiet = lambda *a: True
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('recon_done_eth', '1')")
c.conn.commit()


def opening(chain, ca, w=W):
    r = c.conn.execute("SELECT sum(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                       " WHERE p.source_kind='opening' AND a.address=? AND p.location=?", (ca, f"wallet:{chain}:{w}")).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


print("[H1] (3) 블록스카웃 보유 목록 후보 = 스팸 앵커 필터")
bal1 = c._recon_fetch_plan("eth", "evm", [W], "new")()
c._recon_bal = lambda chain, kind, md, wallets, bal=bal1: bal
c._wrecon_run("eth", "evm", "evm", set(), 1780000000, True, "new", [W])
c.__dict__.pop("_recon_bal", None)
sk1 = (bal1.get("_disc_skip") or {}).get(W) or {}
chk(opening("eth", XS) == 0 and opening("eth", XN) == 0,
    "H1 블록스카웃 목록에만 있는 원장 밖 스팸(유동성 없음 · 스캠 이름) = 잔고가 있어도 기초 잔고 안 함(종전 = 그대로 opening)",
    (opening("eth", XS), opening("eth", XN), sk1))
chk("유동성" in str(sk1.get(XS, "")) and "이름" in str(sk1.get(XN, "")), "H1 스팸 사유 기록(상태 파일 · 점검 도구가 읽음)", sk1)
q1 = set((bal1.get("_queried") or {}).get(W) or ())
chk(XS not in q1 and XN not in q1 and XL in q1, "H1 스팸 칸 = 조회 범위(_q) 밖(미관측 — rebuild2 도 앵커를 지어내지 않음)", sorted(x[:6] for x in q1))
chk(opening("eth", XL) == BAL[XL] and opening("eth", XE) == BAL[XE],
    "H1 덱스 유동성 있는 블록스카웃 목록 토큰 · 발견 토큰 = 종전처럼 기초 잔고", (opening("eth", XL), opening("eth", XE)))
pay1 = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id=?", (f"recon:eth:{W}",)).fetchone()[0])
chk(f"token:{XS}" not in pay1.get(W, {}) and pay1.get(W, {}).get(f"token:{XL}") == BAL[XL],
    "H1 관측 payload = 스팸 칸 없음 · 정상 칸 그대로(rebuild2 재료)", sorted(pay1.get(W, {})))
c.cfg["token_discovery"] = {"enabled": False}
bal1b = c._recon_fetch_plan("eth", "evm", [W], "new")()
chk(("token", XS) in ((bal1b.get("per_wallet") or {}).get(W) or {}), "H1 발견 끔 = 종전 그대로(블록스카웃 목록 그대로 조회 · 필터 없음)",
    sorted(str(k[1])[:6] for k in ((bal1b.get("per_wallet") or {}).get(W) or {})))
c.cfg.pop("token_discovery", None)

print("[H2] (4) 잔고 대조 — 일시 보류(덱스 장애) 토큰 다시 판정")
import balcheck

HX, HY, HZ, HW = "0x" + "e1" * 20, "0x" + "e2" * 20, "0x" + "e3" * 20, "0x" + "e4" * 20
HOLD = "일시 보류 — 판정 출처 장애"
SIG2 = dict(td.wallet_sig(c.conn, "eth", W), nat="5")
td.update_state(lambda cur: {"v": 1, "pairs": {f"eth:{W}": {
    "at": int(time.time()), "sig": SIG2, "cas": {HX: ["etherscan"], HY: ["etherscan"], HZ: ["etherscan"]},
    "meta": {HX: {"sym": "HOLDX", "dec": 18}, HY: {"sym": "HOLDY", "dec": 18}, HZ: {"sym": "HOLDZ", "dec": 18}},
    "skip": {HX: HOLD, HY: HOLD, HZ: HOLD}, "ok": {s9: 1 for s9 in td.INDEX_SOURCES + ("rabby", "logs")}, "fail": {}}}})
DEX2 = []


def fake_dex2(chain, cas, min_reserve=10000.0, sleep=None):
    DEX2.append(sorted(cas))
    out = {}
    for ca in cas:
        if ca == HX:
            out[ca] = (True, 50000.0, 3.0, "HOLDX")
        elif ca == HY:
            out[ca] = (False, 10.0, None, "HOLDY")
    return out


td.dex_check = fake_dex2
ONC = {HX: 1000 * E18, HY: 1000 * E18, HZ: 1000 * E18}


def fake_rpc(u, method, params, timeout=25.0, gap=True):
    if method == "eth_getBalance":
        return "0x5"
    if method == "eth_call":
        to = params[0]["to"].lower()
        return hex(ONC.get(to, 0)) if params[0]["data"].startswith("0x70a08231") else hex(18)
    raise AssertionError(method)


recon._rpc = fake_rpc
balcheck.time.sleep = lambda s: None
td.discover = lambda *a, **k: {"cas": {}, "meta": {}, "ok": {x: 0 for x in (k.get("sources") or [])}, "fail": {}, "calls": {}}
cfg2 = dict(common.load_config(), backfill_months=0)
cfg2["wallets"] = [{"type": "evm", "chain": "eth", "address": W}]
s2 = {}
try:
    s2 = balcheck.run_once(cfg2, c.conn, {}, set(), {})
except Exception as e:
    chk(False, "H2 잔고 대조 실행", repr(e)[:200])
mm2 = {m.get("ca"): m for m in s2.get("mismatches") or []}
chk(HX in mm2 and mm2[HX]["onchain"] == 1000.0 and mm2[HX]["ledger"] == 0.0 and mm2[HX]["diffUsd"] == 3000.0,
    "H2 일시 보류 · 가격 없던 토큰 → 덱스 재판정 '믿을 만함' = 그 가격으로 대조 → 빠진 보유가 불일치로 드러남(종전 = 영구 제외 · 무음)",
    (sorted(mm2), s2.get("errors")))
chk(HY not in mm2 and HZ not in mm2, "H2 스팸 판정·여전히 모름 = 불일치로 안 띄움", sorted(x[:6] for x in mm2))
e2 = (td.load_state().get("pairs") or {}).get(f"eth:{W}") or {}
sk2, me2 = e2.get("skip") or {}, e2.get("meta") or {}
chk(HX not in sk2 and float((me2.get(HX) or {}).get("px") or 0) == 3.0, "H2 믿을 만함 = 상태 skip 지움 · 가격 저장(다음 판부터 보통 후보)", (sk2.get(HX), me2.get(HX)))
chk("유동성" in str(sk2.get(HY, "")) and td.skip_final(sk2.get(HY, "")), "H2 유동성 부족 = 최종 skip(다시 안 봄)", sk2.get(HY))
chk(str(sk2.get(HZ, "")).startswith("일시 보류") and (me2.get(HZ) or {}).get("dexAt"), "H2 덱스 장애 그대로 = 보류 유지 · 재판정 시각 기록", (sk2.get(HZ), me2.get(HZ)))
ds2 = s2.get("disc") or {}
chk(ds2.get("hold") == 1 and ds2.get("skip") == 1, "H2 발견 요약 = 판정 대기 1(HZ) · 스팸 의심 1(HY) 따로 셈(종전 = 일시 보류도 '스팸 의심'으로)", ds2)
n2 = len(DEX2)
s2b = {}
try:
    s2b = balcheck.run_once(cfg2, c.conn, {}, set(), s2)
except Exception as e:
    chk(False, "H2 두 번째 판", repr(e)[:200])
chk(len(DEX2) == n2 and any(m.get("ca") == HX for m in s2b.get("mismatches") or []),
    "H2 1시간 안 두 번째 판 = 덱스 0콜(보류 HZ 다시 안 물음) · HX 는 보통 후보로 계속 대조", (DEX2[n2:], [m.get("ca", "")[:6] for m in s2b.get("mismatches") or []]))
td.update_state(lambda cur: (cur["pairs"][f"eth:{W}"]["meta"][HZ].update(dexAt=1), cur)[1])
td.dex_check = lambda chain, cas, min_reserve=10000.0, sleep=None: DEX2.append(sorted(cas)) or {ca: (True, 20000.0, 1.0, "HOLDZ") for ca in cas}
s2c = {}
try:
    s2c = balcheck.run_once(cfg2, c.conn, {}, set(), s2b)
except Exception as e:
    chk(False, "H2 세 번째 판", repr(e)[:200])
chk(DEX2[n2:] == [[HZ]] and any(m.get("ca") == HZ for m in s2c.get("mismatches") or []) and (s2c.get("disc") or {}).get("hold") == 0,
    "H2 간격 지나면 다시 판정(그 토큰만) · 덱스 복구 = 대조 · 판정 대기 0", (DEX2[n2:], (s2c.get("disc") or {}).get("hold")))


def _h2_unit():
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{W}2": {
        "at": 1, "cas": {HX: ["ankr"], HY: ["etherscan"], HZ: ["etherscan"], HW: ["ankr"]}, "skip": {HX: HOLD, HY: HOLD, HZ: HOLD, HW: HOLD},
        "meta": {}}})))
    b9 = [5]
    calls9 = []

    def boom(chain, cas, mr=0, sleep=None):
        calls9.append(list(cas))
        raise RuntimeError("시험: 덱스스크리너 장애")
    r9 = td.rejudge_hold("eth", W + "2", [(HX, ["ankr"], {"sym": "HOLDX", "wl": True, "px": 2.0}), (HY, ["etherscan"], {"sym": "HOLDY"}),
                                          (HW, ["ankr"], {"sym": "HOLDW", "wl": True})], 10000.0, budget=b9, now=NOW, dex=boom)
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}2") or {}
    chk(b9 == [0] and len(calls9) == 1 and {x[0] for x in r9} == {HX, HY, HW} and HX not in (e9.get("skip") or {})
        and str((e9.get("skip") or {}).get(HY, "")).startswith("일시 보류"),
        "H2 덱스 전면 장애 = 이번 판 재판정 멈춤(1콜) · 정적으로 믿을 만하고 가격 아는 것(Ankr 정품 목록)은 보류 풂 · 나머지 보류 유지", (b9, calls9, e9.get("skip")))
    chk(str((e9.get("skip") or {}).get(HW, "")).startswith("일시 보류"),
        "R1 (hq462) 정적으로 믿을 만해도 가격을 모르면 보류 유지(대조·재판정·판정 대기 경고가 사라지지 않게)", (e9.get("skip") or {}).get(HW))
    r9b = td.rejudge_hold("eth", W + "2", [(HZ, ["etherscan"], {"sym": "HOLDZ"})], 10000.0, budget=b9, now=NOW, dex=boom)
    chk(len(calls9) == 1 and [x[0] for x in r9b] == [HZ], "H2 예산 0 = 덱스 0콜 · 그대로 돌려줌(다음 판)", calls9)


_try(_h2_unit, "H2 재판정 단위(장애·예산)")


def _h2_health():
    import health as H
    hs = H.settings({"health": {"units": ["tj-core", "tj-web"]}})
    obs = {"now": NOW, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in ("tj-core", "tj-web")}, "bal_mem": {}, "prev_inc": {},
           "sources": [], "balcheck": {"checkedAt": NOW, "confirmed": 0, "watch": 0, "resolving": 0, "errors": 0, "top": None, "items": [],
                                       "unchecked": 0, "capped": False, "pairs": 1,
                                       "disc": {"pairs": 1, "done": 1, "failPairs": 0, "failBy": {}, "skip": 1, "hold": 2, "chains": {}, "noOld": []}}}
    ev = {c9["id"]: c9 for c9 in H.evaluate(obs, hs)}
    d9 = ev.get("balcheck:disc") or {}
    chk(d9.get("level") == "warn" and "판정 대기" in str(d9.get("title")) + str(d9.get("detail")) and "2" in str(d9.get("title")),
        "H2 상태 패널 '토큰 발견' 줄 = 판정 대기 2 주의(노랑 · 알림 없음) — 무음 아님", {k: d9.get(k) for k in ("level", "title", "detail", "notify")})
    chk(not d9.get("notify"), "H2 판정 대기 = 텔레그램 알림 없음(사이트만)", d9.get("notify"))


_try(_h2_health, "H2 상태 패널 판정 대기 줄")

print("[H3] (5) BSC 지갑별 대사 — 일시 보류로 뺀 토큰의 늦은 레그를 허위 opening 으로 흡수하지 않음")
BA, BB, BC = "0x" + "f1" * 20, "0x" + "f2" * 20, "0x" + "f3" * 20
X = "0x" + "b7" * 20
TB = NOW - 5 * 86400
c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"wrecon_done:bsc:{W}", str(TB)))
c.conn.execute("INSERT OR REPLACE INTO raw_observations (obs_id, kind, venue, payload, observed_at) VALUES (?,?,?,?,?)",
               (f"recon:bsc:{W}", "opening_balance", "bsc", json.dumps({W: {"native:None": 0, f"token:{BA}": 0, f"token:{BC}": 6 * E18}}), TB))
aids = {ca: c.asset_id("token", "bsc", ca, symbol=s9, decimals=18) for ca, s9 in ((BA, "BTA"), (BB, "BTB"), (BC, "BTC"))}
c.conn.commit()


def late(hx, ca, qty, ts, blk):
    snap = {"tx": {"hash": hx, "from": X, "to": W, "timestamp": ts, "block_number": blk, "status": "ok"}}
    c.conn.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('bsc',?,?,?,?,?,?,?)",
                   (hx, blk, "0x" + "d" * 64, ts, json.dumps(snap), json.dumps([W]), NOW))
    before = c._tx_wallet_sums("bsc", hx)
    c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'bsc', ?, 0, ?, ?, ?, ?, NULL, NULL, 'transfer', 'TRANSFER_IN', 3)",
                   (hx, ts, aids[ca], f"wallet:bsc:{W}", str(qty)))
    n9 = c._anchor_absorb("bsc", hx, before)
    c.conn.commit()
    return n9


def cell(ca):
    return sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE location=? AND asset_id=?", (f"wallet:bsc:{W}", aids[ca])))


def anc(ca):
    return [int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE source_kind='opening' AND source_id=? AND asset_id=?",
                                              (f"recon:bsc:{W}", aids[ca]))]


def _h3():
    h1 = "0x" + "%064x" % 0x31
    late(h1, BB, 5 * E18, TB - 3600, 100)
    chk(anc(BB) == [] and cell(BB) == 5 * E18,
        "H3 일시 보류로 뺀 칸(BSC 관측 payload 에 키 없음)의 늦은 유입 = 앵커 흡수 없음 · 원장 +5 그대로(종전 = 허위 opening −5 · 합 0)", (anc(BB), cell(BB)))
    h2 = "0x" + "%064x" % 0x32
    late(h2, BA, 3 * E18, TB - 3600, 101)
    chk(anc(BA) == [-3 * E18] and cell(BA) == 0, "H3 조회했고 0 인 칸(키 = 0)의 늦은 유입 = 종전처럼 앵커가 흡수(−3 · 합 0 = 관측 잔고)", (anc(BA), cell(BA)))
    h3 = "0x" + "%064x" % 0x33
    late(h3, BC, 2 * E18, TB - 3600, 102)
    chk(anc(BC) == [-2 * E18], "H3 조회했고 잔고 있는 칸 = 종전처럼 흡수", anc(BC))
    h4 = "0x" + "%064x" % 0x34
    late(h4, BB, 1 * E18, TB + 3600, 103)
    chk(anc(BB) == [], "H3 대사 뒤 유입 = 흡수 대상 아님(종전 그대로)", anc(BB))
    n9 = c._anchor_absorb("bsc", h1, c._tx_wallet_sums("bsc", h1))
    chk(n9 == 0 and anc(BB) == [] and anc(BA) == [-3 * E18], "H3 멱등 — 같은 재기장 다시 = 보정 0", (n9, anc(BB), anc(BA)))
    c2 = core.Core(common.load_config())
    chk(c2._obs_tok_observed(f"recon:bsc:{W}", W, BB) is False and c2._obs_tok_observed(f"recon:bsc:{W}", W, BA) is True
        and c2._obs_tok_observed(f"recon:bsc:{W}", W.upper().replace("0X", "0x"), BC.upper().replace("0X", "0x")) is True,
        "H3 재시작 뒤 같은 판정(키 없음 = 미관측 · 0 키 = 관측 · 대소문자 무관)", "")
    h5 = "0x" + "%064x" % 0x35
    snap5 = {"tx": {"hash": h5, "from": X, "to": W, "timestamp": TB - 7200, "block_number": 99, "status": "ok"}}
    c2.conn.execute("INSERT OR REPLACE INTO raw_txs (chain, txhash, block, blockhash, ts, snapshot, wallets, ingested_at) VALUES ('bsc',?,?,?,?,?,?,?)",
                    (h5, 99, "0x" + "d" * 64, TB - 7200, json.dumps(snap5), json.dumps([W]), NOW))
    c2.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                    " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'bsc', ?, 0, ?, ?, ?, ?, NULL, NULL, 'transfer', 'TRANSFER_IN', 3)",
                    (h5, TB - 7200, aids[BB], f"wallet:bsc:{W}", str(E18)))
    c2._note_pre_window("bsc", TB - 7200, h5)
    c2.conn.commit()
    chk(c2._meta_get(f"ext_prewindow_tx:bsc:{h5}") is None, "H3 미관측 칸만 건드린 늦은 옛 거래 = 재구축 표식 없음(rebuild2 observed 와 같은 규칙)",
        c2._meta_get(f"ext_prewindow_tx:bsc:{h5}"))
    c2.conn.close()


_try(_h3, "H3 BSC 지갑별 대사 관측")

print("[R] (hq462) 재판정 보강 — 가격 없는 믿음 · 발견 갱신 · 블록스카웃 단독 보류 · 호출 단위 · 원장 칸 보류")
RP, RQ, XB, HL = "0x" + "a7" * 20, "0x" + "a8" * 20, "0x" + "a9" * 20, "0x" + "aa" * 20


def _r1():
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{W}3": {
        "at": 1, "cas": {RP: ["etherscan"], RQ: ["etherscan"]}, "skip": {RP: HOLD, RQ: HOLD}, "meta": {}}})))
    td.rejudge_hold("eth", W + "3", [(RP, ["etherscan"], {"sym": "RPT"}), (RQ, ["etherscan"], {"sym": "RQT"})], 10000.0, now=NOW,
                    dex=lambda ch, cas, mr=0, sleep=None: {RP: (True, 50000.0, None, "RPT"), RQ: (True, 50000.0, 4.0, "RQT")})
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}3") or {}
    chk(str((e9.get("skip") or {}).get(RP, "")).startswith("일시 보류") and (e9.get("meta") or {}).get(RP, {}).get("dexAt"),
        "R1 덱스 '믿음'인데 가격 없음(quote 쪽만·priceUsd null) = 보류 유지(종전 = 보류 풀려 대조 제외 · 판정 대기도 0 — 무음)", e9.get("skip"))
    chk(RQ not in (e9.get("skip") or {}) and (e9.get("meta") or {}).get(RQ, {}).get("px") == 4.0, "R1 가격까지 얻은 믿음 = 보류 풂 · 가격 저장", e9.get("meta"))
    td.save_result("eth", W + "3", {"cas": {RP: ["etherscan"], RQ: ["etherscan"]}, "meta": {RQ: {"sym": "RQT", "dec": 18}, RP: {"sym": "RPT"}},
                                    "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, {"txn": 9}, "changed:txn")
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}3") or {}
    m9 = (e9.get("meta") or {}).get(RQ) or {}
    chk(m9.get("px") == 4.0 and m9.get("dexAt") and m9.get("dec") == 18 and (e9.get("meta") or {}).get(RP, {}).get("dexAt"),
        "R2 발견 갱신 뒤에도 재판정 가격·시각 유지(새 발견 값은 반영) — 종전 = 가격 사라져 다음 판부터 대조 제외(무음)", e9.get("meta"))


_try(_r1, "R1·R2 가격 없는 믿음 · 발견 갱신")


def _r3():
    bal9 = {"per_wallet": {W: {("token", XB): 500 * E18}}, "_meta": {XB: ("BSONLY", 18)}, "_queried": {W: [XB]}, "_unobs": {}, "_extra_only": {W: [XB]},
            "_source": "rpc", "_block": 900}

    def boom(ch, cas, mr=0, sleep=None):
        raise RuntimeError("시험: 덱스 장애")
    out9 = td.filter_result(bal9, {"chain": "eth", "strict": None, "confirmed": set(), "min_reserve": 10000.0, "off": False},
                            {"meta": {}, "src": {}, "status": {}}, dex=boom)
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}") or {}
    chk(("token", XB) not in out9["per_wallet"][W] and str((e9.get("skip") or {}).get(XB, "")).startswith("일시 보류")
        and "recon" in ((e9.get("cas") or {}).get(XB) or []) and (e9.get("meta") or {}).get(XB, {}).get("sym") == "BSONLY"
        and (e9.get("meta") or {}).get(XB, {}).get("dec") == 18,
        "R3 블록스카웃 단독 후보 일시 보류 = 상태 후보로 남김(출처 recon · 조회 심볼·소수) — 종전 = skip 만 남아 재판정 대상 밖", (e9.get("cas") or {}).get(XB))
    ONC[XB] = 500 * E18
    td.dex_check = lambda chain, cas, min_reserve=10000.0, sleep=None: {ca: (True, 90000.0, 2.0, "BSONLY") for ca in cas}
    s9 = balcheck.run_once(cfg2, c.conn, {}, set(), {})
    m9 = [m for m in s9.get("mismatches") or [] if m.get("ca") == XB]
    chk(m9 and m9[0]["onchain"] == 500.0 and m9[0]["diffUsd"] == 1000.0, "R3 덱스 복구 뒤 잔고 대조가 다시 판정 → 빠진 보유가 불일치로 드러남",
        (m9, s9.get("errors")))
    td.save_result("eth", W, {"cas": {}, "meta": {}, "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, dict(SIG2), "changed:x")
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}") or {}
    chk(XB in (e9.get("cas") or {}) and (e9.get("meta") or {}).get(XB, {}).get("px") == 2.0,
        "R3 발견 갱신(색인 출처가 그 토큰을 모름)에도 recon 출처 후보·가격 유지", (e9.get("cas") or {}).get(XB))


_try(_r3, "R3 블록스카웃 단독 보류")


def _r4():
    many = ["0x%040x" % (0xbb000 + i) for i in range(65)]
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{W}5": {
        "at": 1, "cas": {x: ["etherscan"] for x in many}, "skip": {x: HOLD for x in many}, "meta": {}}})))
    sizes = []
    b9 = [2]
    td.rejudge_hold("eth", W + "5", [(x, ["etherscan"], {"sym": "M%d" % i}) for i, x in enumerate(many)], 10000.0, budget=b9, now=NOW,
                    dex=lambda ch, cas, mr=0, sleep=None: sizes.append(len(cas)) or {x: (True, 30000.0, 1.0, None) for x in cas})
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}5") or {}
    left = [x for x in many if str((e9.get("skip") or {}).get(x, "")).startswith("일시 보류")]
    chk(sizes == [30, 30] and b9 == [0] and len(left) == 5 and not any((e9.get("meta") or {}).get(x, {}).get("dexAt") for x in left),
        "R4 재판정 호출 상한 = 덱스 요청(30개 묶음) 단위 · 상한 밖 토큰은 시각 안 찍고 다음 판", (sizes, b9, len(left)))
    sizes.clear()
    b9 = [5]
    td.rejudge_hold("eth", W + "5", [(x, ["etherscan"], {"sym": "M"}) for x in left], 10000.0, budget=b9, now=NOW,
                    dex=lambda ch, cas, mr=0, sleep=None: sizes.append(len(cas)) or {})
    chk(sizes == [5] and b9 == [0], "R4 첫 묶음 전면 장애 = 그 판 재판정 멈춤", (sizes, b9))


_try(_r4, "R4 호출 단위")


def _r5():
    aid9 = c.asset_id("token", "eth", HL, symbol="HLT", decimals=18)
    c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'eth', ?, 0, ?, ?, ?, ?, NULL, NULL, 'transfer', 'TRANSFER_IN', 3)",
                   ("0x" + "%064x" % 0x51, NOW - 600, aid9, f"wallet:eth:{W}", str(10 * E18)))
    c.conn.commit()

    def _add(cur):
        e9 = cur["pairs"].setdefault(f"eth:{W}", {})
        e9.setdefault("cas", {})[HL] = ["etherscan"]
        e9.setdefault("meta", {})[HL] = {"sym": "HLT", "dec": 18}
        e9.setdefault("skip", {})[HL] = HOLD
        e9["sig"] = dict(td.wallet_sig(c.conn, "eth", W), nat="5")
        return cur
    td.update_state(_add)
    ONC[HL] = 1000 * E18
    s9 = balcheck.run_once(cfg2, c.conn, {}, set(), {})
    m9 = [m for m in s9.get("mismatches") or [] if m.get("ca") == HL]
    chk(m9 and m9[0]["ledger"] == 10.0 and m9[0]["onchain"] == 1000.0 and m9[0]["diffUsd"] == 1980.0,
        "R5 (RECORD) 원장 칸이 생긴 가격 없는 보류 토큰 = 재판정 가격으로 원장 수량과 대조(종전 = 원장·발견 둘 다 제외)", (m9, s9.get("errors")))


_try(_r5, "R5 원장 칸 보류 토큰")

print("[S] (hq467) 보류 → 재판정 상태 전이")
ST, SF = "0x" + "ab" * 20, "0x" + "ac" * 20
td.dex_check = lambda chain, cas, min_reserve=10000.0, sleep=None: {ca: (True, 90000.0, 2.0, "SYM") for ca in cas}


def _t4():
    s1 = balcheck.run_once(cfg2, c.conn, {}, set(), {})
    m1 = [m for m in s1.get("mismatches") or [] if m.get("ca") == HL]
    s2 = balcheck.run_once(cfg2, c.conn, {}, set(), s1)
    m2 = [m for m in s2.get("mismatches") or [] if m.get("ca") == HL]
    chk(m1 and m2 and not m2[0].get("carried") and m2[0]["ledger"] == 10.0 and m2[0]["firstSeen"] == m1[0]["firstSeen"],
        "T4 원장 칸 + 재판정 가격(S3) = 다음 판에도 원장 수량과 대조 · 확정 대기 이어짐(종전 = 다음 판 빠짐 → 확정 전에 사라짐)", (m1, m2))


_try(_t4, "T4 원장 칸 S3 다음 판")


def _t3():
    old = NOW - 7 * 3600

    def _set(cur):
        e9 = cur["pairs"].setdefault(f"eth:{W}", {})
        e9.setdefault("cas", {})[ST] = ["etherscan"]
        e9.setdefault("cas", {})[SF] = ["etherscan"]
        e9.setdefault("meta", {})[ST] = {"sym": "STT", "dec": 18, "px": 0.1, "dexAt": old}
        e9.setdefault("meta", {})[SF] = {"sym": "SFT", "dec": 18, "px": 3.0, "dexAt": old}
        (e9.get("skip") or {}).pop(ST, None)
        (e9.get("skip") or {}).pop(SF, None)
        return cur
    td.update_state(_set)
    ONC[ST] = 1000 * E18
    ONC[SF] = 1000 * E18
    prev = {"pending": {f"eth:{W}:{SF}": NOW - 7200},
            "mismatches": [{"key": f"eth:{W}:{SF}", "wallet": W, "chain": "eth", "sym": "SFT (발견)", "ca": SF, "ledger": 0.0, "onchain": 1000.0,
                            "diffUsd": 3000.0, "firstSeen": NOW - 7200, "confirmed": True}]}
    td.dex_check = lambda chain, cas, min_reserve=10000.0, sleep=None: {ca: (True, 90000.0, 2.0, "STT") for ca in cas if ca == ST}
    s9 = balcheck.run_once(cfg2, c.conn, {}, set(), prev)
    mm9 = {m.get("ca"): m for m in s9.get("mismatches") or []}
    chk(ST in mm9 and mm9[ST]["diffUsd"] == 2000.0, "T3 재판정 가격 만료 → 다시 판정해 새 가격(2.0)으로 대조 → 불일치 드러남(종전 = 7시간 전 0.1 로 $100 — 경고 놓침)",
        (mm9.get(ST), s9.get("errors")))
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{W}") or {}
    chk(float(((e9.get("meta") or {}).get(ST) or {}).get("px") or 0) == 2.0 and ((e9.get("meta") or {}).get(ST) or {}).get("dexAt", 0) > old,
        "T3 만료 재판정 성공 = 가격·시각 갱신(S3 유지)", (e9.get("meta") or {}).get(ST))
    chk(str((e9.get("skip") or {}).get(SF, "")).startswith("일시 보류") and not ((e9.get("meta") or {}).get(SF) or {}).get("px")
        and (s9.get("disc") or {}).get("hold", 0) >= 1,
        "T3 만료 재판정 실패 = 옛 가격 버리고 일시 보류(판정 대기 경고) — 낡은 가격으로 대조하지 않음", ((e9.get("skip") or {}).get(SF), (e9.get("meta") or {}).get(SF)))
    chk(SF in mm9 and mm9[SF].get("carried") and f"eth:{W}:{SF}" in (s9.get("pending") or {}),
        "T6 대조 못 한 보류 칸 = 지난 불일치·확정 대기 이월(사라지지 않음)", (mm9.get(SF), (s9.get("pending") or {}).get(f"eth:{W}:{SF}")))


_try(_t3, "T3·T6 가격 만료")


def _t5():
    k5 = W + "6"
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k5}": {
        "at": 1, "cas": {XB: ["recon"]}, "skip": {XB: HOLD}, "meta": {XB: {"sym": "BSONLY", "dec": 18}}}})))
    td.save_result("eth", k5, {"cas": {XB: ["etherscan"]}, "meta": {XB: {"sym": "BSONLY"}}, "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, {}, "changed:x")
    e1 = (td.load_state().get("pairs") or {}).get(f"eth:{k5}") or {}
    td.save_result("eth", k5, {"cas": {}, "meta": {}, "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, {}, "changed:y")
    e2 = (td.load_state().get("pairs") or {}).get(f"eth:{k5}") or {}
    chk(set((e1.get("cas") or {}).get(XB) or []) == {"etherscan", "recon"} and "recon" in ((e2.get("cas") or {}).get(XB) or [])
        and str((e2.get("skip") or {}).get(XB, "")).startswith("일시 보류"),
        "T5 recon 후보가 재발견돼도 recon 표식 유지 → 그 뒤 발견에서 빠져도 후보 유지(재판정 끊김 없음)", ((e1.get("cas") or {}).get(XB), (e2.get("cas") or {}).get(XB)))
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k5}": {
        "at": 1, "cas": {RP: ["etherscan"], RQ: ["etherscan"], ST: ["etherscan"]}, "skip": {RP: HOLD},
        "meta": {RQ: {"sym": "RQT", "px": 4.0, "dexAt": NOW}, ST: {"sym": "STT", "px": 1.0}}}})))
    td.save_result("eth", k5, {"cas": {}, "meta": {}, "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, {}, "changed:z")
    e3 = (td.load_state().get("pairs") or {}).get(f"eth:{k5}") or {}
    chk(RP in (e3.get("cas") or {}) and RQ in (e3.get("cas") or {}) and ((e3.get("meta") or {}).get(RQ) or {}).get("px") == 4.0
        and ST not in (e3.get("cas") or {}),
        "T5 새 발견이 몰라도 보류(S1)·재판정 가격(S3) 후보 유지 · 상태 없는 보통 후보는 종전처럼 새 결과대로", sorted(x[:6] for x in (e3.get("cas") or {})))


_try(_t5, "T5 재발견 recon 표식")


def _t7():
    k7 = W + "7"
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k7}": {
        "at": 1, "cas": {RP: ["etherscan"]}, "skip": {RP: HOLD}, "meta": {}}})))
    imp = getattr(td, "_DEX_IMPL", None)
    saved = td.dex_check, td._http
    calls = []

    def fake_http(url, **kw):
        calls.append(kw.get("retries"))
        raise td.SourceFail("http", "시험: 503")
    try:
        if imp is not None:
            td.dex_check = imp
        td._http = fake_http
        b9 = [5]
        td.rejudge_hold("eth", k7, [(RP, ["etherscan"], {"sym": "RPT"})], 10000.0, budget=b9, now=NOW)
    finally:
        td.dex_check, td._http = saved
    chk(calls == [1] and b9 == [0], "T7 재판정 호출 = 실제 HTTP 1요청(재시도 없음) · 전면 장애 = 그 판 멈춤(종전 = 요청 안 재시도 2회)", (calls, b9))


_try(_t7, "T7 실제 HTTP 수")

print("[U] (hq476) 예산 밖 만료 · S2 보존 제외 · 현재 제외 판정 이월 금지 · 요약 = 지금 지갑만")
UA, UB, UC, UD = "0x" + "c4" * 20, "0x" + "c5" * 20, "0x" + "c6" * 20, "0x" + "c7" * 20


def _u1():
    k9 = W + "8"
    old = NOW - 7 * 3600
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k9}": {
        "at": 1, "cas": {UA: ["etherscan"], UB: ["etherscan"]}, "skip": {}, "meta": {UA: {"sym": "UAT", "px": 1.0, "dexAt": old},
                                                                                    UB: {"sym": "UBT", "px": 1.0, "dexAt": old}}}})))
    b9 = [0]
    r9 = td.rejudge_hold("eth", k9, [(UA, ["etherscan"], {"sym": "UAT", "px": 1.0, "dexAt": old, "_stale": True})], 10000.0, budget=b9, now=NOW,
                         dex=lambda *a, **k: (_ for _ in ()).throw(AssertionError("예산 0 인데 호출")))
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{k9}") or {}
    chk(str((e9.get("skip") or {}).get(UA, "")).startswith("일시 보류") and not ((e9.get("meta") or {}).get(UA) or {}).get("px")
        and ((e9.get("meta") or {}).get(UA) or {}).get("dexAt") == old and not (r9 and r9[0][2].get("px")),
        "U1 요청 예산 밖 만료 S3 = 호출 없이 S1 '시세 갱신 대기'로 저장(판정 대기 경고에 보임 · 재시도 시각 그대로)", ((e9.get("skip") or {}).get(UA), (e9.get("meta") or {}).get(UA)))
    many = ["0x%040x" % (0xcc000 + i) for i in range(35)]
    td.update_state(lambda cur: (cur["pairs"][f"eth:{k9}"]["cas"].update({x: ["etherscan"] for x in many}),
                                 cur["pairs"][f"eth:{k9}"]["meta"].update({x: {"sym": "M", "px": 1.0, "dexAt": old} for x in many}), cur)[2])
    b9 = [1]
    td.rejudge_hold("eth", k9, [(x, ["etherscan"], {"sym": "M", "px": 1.0, "dexAt": old, "_stale": True}) for x in many], 10000.0, budget=b9, now=NOW,
                    dex=lambda ch, cas, mr=0, sleep=None: {x: (True, 30000.0, 2.0, "M") for x in cas})
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{k9}") or {}
    left = [x for x in many if str((e9.get("skip") or {}).get(x, "")).startswith("일시 보류")]
    fresh = [x for x in many if ((e9.get("meta") or {}).get(x) or {}).get("px") == 2.0 and x not in (e9.get("skip") or {})]
    chk(len(fresh) == 30 and len(left) == 5, "U1 묶음 상한 밖 만료 S3(5) = S1 '시세 갱신 대기' · 물은 30 = 새 가격 S3", (len(fresh), len(left)))


_try(_u1, "U1 예산 밖 만료")


def _u2():
    k9 = W + "9"
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k9}": {
        "at": 1, "cas": {UA: ["etherscan"], UB: ["recon"], UC: ["etherscan"]},
        "skip": {UA: "유동성 부족 — 스팸 의심", UB: "유동성 부족 — 스팸 의심", UC: HOLD},
        "meta": {UA: {"sym": "UAT", "dexAt": NOW}, UB: {"sym": "UBT", "dexAt": NOW}, UC: {"sym": "UCT"}}}})))
    td.save_result("eth", k9, {"cas": {}, "meta": {}, "ok": {"etherscan": 1}, "fail": {}, "calls": {}}, {}, "changed:q")
    e9 = (td.load_state().get("pairs") or {}).get(f"eth:{k9}") or {}
    chk(UA not in (e9.get("cas") or {}) and UB not in (e9.get("cas") or {}) and UC in (e9.get("cas") or {}),
        "U2 재발견 보존 = S1·S3·recon 만 — 최종 제외(S2) 후보는 재판정 시각·recon 표식이 있어도 새 결과대로(스팸 영구 보존 안 함)", sorted(x[:6] for x in (e9.get("cas") or {})))


_try(_u2, "U2 S2 보존 제외")


def _u3():
    aid9 = c.asset_id("token", "eth", UD, symbol="UDT", decimals=18)
    c.conn.execute("INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd, cost_krw,"
                   " leg_kind, event, classifier_ver) VALUES ('chain_tx', 'eth', ?, 0, ?, ?, ?, ?, NULL, NULL, 'transfer', 'TRANSFER_IN', 3)",
                   ("0x" + "%064x" % 0x61, NOW - 600, aid9, f"wallet:eth:{W}", str(5 * E18)))
    c.conn.commit()
    gid9 = c.conn.execute("SELECT group_id FROM assets WHERE asset_id=?", (aid9,)).fetchone()[0]

    def _add(cur):
        e9 = cur["pairs"].setdefault(f"eth:{W}", {})
        e9.setdefault("cas", {}).update({UC: ["etherscan"], UD: ["etherscan"]})
        e9.setdefault("meta", {}).update({UC: {"sym": "Visit claim-reward.com", "dexAt": NOW}, UD: {"sym": "UDT", "dexAt": NOW}})
        e9.setdefault("skip", {}).update({UC: HOLD, UD: HOLD})
        e9["sig"] = dict(td.wallet_sig(c.conn, "eth", W), nat="5")
        return cur
    td.update_state(_add)

    def mm(ca, fs):
        return {"key": f"eth:{W}:{ca}", "wallet": W, "chain": "eth", "sym": "X", "ca": ca, "ledger": 0.0, "onchain": 900.0, "diffUsd": 900.0,
                "firstSeen": fs, "confirmed": True}
    prev = {"pending": {f"eth:{W}:{UC}": NOW - 90000, f"eth:{W}:{UD}": NOW - 90000}, "mismatches": [mm(UC, NOW - 90000), mm(UD, NOW - 90000)]}
    s9 = balcheck.run_once(cfg2, c.conn, {}, {gid9}, prev)
    ks = {m.get("ca") for m in s9.get("mismatches") or []}
    chk(UC not in ks and UD not in ks and f"eth:{W}:{UC}" not in (s9.get("pending") or {}) and f"eth:{W}:{UD}" not in (s9.get("pending") or {}),
        "U3 지금 제외 판정(스캠 이름 · 격리·숨김 그룹) 토큰의 지난 불일치 = 이월 안 함(종전 = 가격 없음 이월로 확정·알림 유지)", sorted(str(x)[:6] for x in ks))
    OK9 = "0x" + "c8" * 20
    prev5 = {"pending": dict(prev["pending"], **{f"eth:{W}:{OK9}": NOW - 90000}),
             "mismatches": [mm(UC, NOW - 90000), mm(UD, NOW - 90000), mm(OK9, NOW - 90000)]}
    s5 = balcheck.run_once(dict(cfg2, balance_check={"max_calls": 1}), c.conn, {}, {gid9}, prev5)
    ks5 = {m.get("ca"): m for m in s5.get("mismatches") or []}
    pd5 = s5.get("pending") or {}
    chk(s5.get("capped") and UC not in ks5 and UD not in ks5 and f"eth:{W}:{UC}" not in pd5 and f"eth:{W}:{UD}" not in pd5,
        "U5 부분 판(호출 상한)에서도 지금 제외 판정 토큰의 지난 불일치·확정 대기 = 이월 안 함(종전 = 부분 판 이월로 되살아나 알림)",
        (s5.get("capped"), sorted(str(x)[:6] for x in ks5), sorted(str(k)[-6:] for k in pd5)))
    chk(OK9 in ks5 and ks5[OK9].get("carried") and f"eth:{W}:{OK9}" in pd5, "U5 부분 판 — 제외 아닌 토큰의 지난 불일치는 종전처럼 이월",
        (ks5.get(OK9), pd5.get(f"eth:{W}:{OK9}")))


_try(_u3, "U3 현재 제외 판정 이월 금지")


def _u4():
    k9 = "0x" + "9d" * 20
    td.update_state(lambda cur: dict(cur, pairs=dict(cur.get("pairs") or {}, **{f"eth:{k9}": {
        "at": 1, "cas": {UA: ["etherscan"]}, "skip": {UA: HOLD}, "meta": {}, "fail": {"alchemy": "http: 503"}}})))
    sm = td.summary(cfg2)
    sm_all = td.summary()
    chk(sm_all.get("hold", 0) > sm.get("hold", 0) and sm_all.get("failPairs", 0) > sm.get("failPairs", 0),
        "U4 (RECORD) 발견 요약 = 지금 등록·추적 중인 지갑만(삭제 지갑·끈 체인의 판정 대기·실패는 경고에서 뺌)", (sm.get("hold"), sm_all.get("hold"), sm.get("failPairs"), sm_all.get("failPairs")))


_try(_u4, "U4 요약 = 지금 지갑")
c.conn.close()
T.finish()
