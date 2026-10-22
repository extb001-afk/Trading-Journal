#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import Reader  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import address_codec as ac  # noqa: E402
import chain_registry as reg  # noqa: E402

chk = T.chk
SOL_A = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_SYS = "11111111111111111111111111111111"
EVM_A = "0x" + "ab" * 20
EVM_TX = "0x" + "cd" * 32
TRON_K = N.OWN["tron"][0]
TRON_D = ac.tron_display(TRON_K)
TON_K = N.OWN["ton"][0]
TON_F = ac.ton_friendly(TON_K)
BTC_ID = reg.btc_source({"mode": "address", "address": N.BTC_ADDR})["key"]
BTC_P2PKH = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"

want = {TRON_K: "tron", TRON_D: "tron", N.OWN["sui"][0]: "sui", TON_K: "ton", TON_F: "ton", "0:" + "31" * 32: "ton",
        N.BTC_ADDR: "btc", BTC_P2PKH: "btc", BTC_ID: "btc"}
got = {k: getattr(reg, "key_chain", lambda x: "없음")(k) for k in want}
chk(got == want, "K key_chain: 원장 키·표시 꼴 → 체인(tron·sui·ton·btc)", {k[:12]: v for k, v in got.items() if v != want[k]})
none_in = [SOL_A, SOL_SYS, EVM_A, "", None, "T" + "1" * 33, "41" + "zz" * 20, "0_" + "00" * 32, "not an address", "multi", "?", "wd:abc"]
chk(all(getattr(reg, "key_chain", lambda x: "없음")(x) is None for x in none_in),
    "K key_chain: 솔라나·EVM 0x40·체크섬 틀린 T…·빈 값·특수 목적지 = None",
    [x for x in none_in if getattr(reg, "key_chain", lambda x: "없음")(x) is not None])
kp = getattr(reg, "key_parse", lambda x: None)
chk(kp(TRON_D) == ("tron", TRON_K) and kp(TON_F) == ("ton", TON_K) and kp(N.BTC_ADDR.upper()) == ("btc", N.BTC_ADDR),
    "K key_parse: 표시 꼴 → 원장 키(T… → 41… · UQ… → 0_… · BTC bech32 대문자 → 소문자)", (kp(TRON_D), kp(TON_F), kp(N.BTC_ADDR.upper())))

import addr_ai  # noqa: E402

chk(addr_ai.fam(EVM_A) == "evm" and addr_ai.fam(SOL_A) == "sol" and addr_ai.fam(SOL_SYS) == "sol" and addr_ai.fam("multi") is None,
    "G fam: EVM·솔라나 종전 그대로")
bad = {x: addr_ai.fam(x) for x in (TRON_K, TRON_D, BTC_P2PKH, BTC_ID, N.BTC_ADDR, TON_K, N.OWN["sui"][0])}
chk(all(v is None for v in bad.values()), "G fam: 새 체인 주소 = None(솔라나 오인 없음)", {k[:12]: v for k, v in bad.items() if v})
chk(addr_ai.akey(TRON_K) is None and addr_ai.akey(SOL_A) == "sol:" + SOL_A, "G akey: Tron 키 = 대상 아님 · 솔라나 그대로")


import xchain_match  # noqa: E402


def _row(ns, txh, wallet, ev="TRANSFER_IN", leg="acq", loc=None, gid=7, cost=None, addr="tok"):
    return {"event": ev, "leg_kind": leg, "cost_usd": cost, "location": loc or f"wallet:{ns}:{wallet}", "source_id": txh,
            "address": addr, "group_id": gid, "asset_id": gid, "decimals": 6, "qty_base": "5000000", "source_ns": ns,
            "symbol": "TKA", "event_ts": 1_700_000_000}


rows = [_row("eth", "0x" + "e1" * 32, EVM_A, addr="0x" + "a1" * 20), _row("sol", "5" * 88, SOL_A, addr=SOL_SYS),
        _row("tron", "f1" * 32, TRON_K, addr=N.TOK["tron"]), _row("sui", "Hx9" + "a" * 40, N.OWN["sui"][0], addr="mv_x"),
        _row("ton", TON_K + ".1." + "f2" * 32, TON_K, addr=TON_K), _row("btc", "f3" * 32, BTC_ID, addr="bt")]
rows.append(_row("eth", "0x" + "e9" * 32, EVM_A, ev="TRANSFER_OUT_EX", leg="move_out", loc="ex:binance"))
cs = xchain_match.candidates(rows, {}, frozenset(), frozenset(), now=1_700_000_100)
chk(sorted(c9["chain"] for c9 in cs) == ["eth", "sol"], "C 역추적 후보 = EVM·솔라나만(새 체인 유입 4건 제외)", [c9["chain"] for c9 in cs])
seed = {"evm_contracts": {"0x" + "b1" * 20: {"proto": "x"}, N.EXT["tron"]: {"proto": "x"}}}
srows = [_row("eth", "0x" + "e2" * 32, EVM_A, ev="TRANSFER_OUT", leg="move_in", loc="out:eth:0x" + "b1" * 20),
         _row("tron", "f4" * 32, TRON_K, ev="TRANSFER_OUT", leg="move_in", loc="out:tron:" + N.EXT["tron"])]
ss = xchain_match.send_candidates(srows, {}, seed, now=1_700_000_100)
chk([c9["chain"] for c9 in ss] == ["eth"], "C 출발 id 후보 = EVM 만(새 체인 출발 제외)", [c9["chain"] for c9 in ss])

import config  # noqa: E402
import core  # noqa: E402
import search_index as si  # noqa: E402

CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": TRON_D}, {"chain": "ton", "address": TON_F}]
json.dump(cfg, open(CFG_PATH, "w"))
c = core.Core(config.load_config())
U_TR, H_TON = "f1" * 32, "f2" * 32
U_TON = TON_K + ".5." + H_TON
c._drain_stream("tron", Reader([N.rec("tron", U_TR, 1_700_000_000, [(TRON_K, "native", 5_000_000)])]), 0, 0)
c._drain_stream("ton", Reader([N.rec("ton", U_TON, 1_700_000_100, [(TON_K, "native", 7_000_000_000)], txhash=H_TON)]), 0, 0)
c.conn.commit()
docs = list(si.ledger_tx_docs(c.conn, {}))
c.conn.close()
by = {d["chain"]: d for d in docs}
chk(by.get("ton", {}).get("tx") == H_TON and by.get("ton", {}).get("key") == "tx:ton:" + U_TON and by.get("tron", {}).get("tx") == U_TR,
    "A TON tx 문서 tx = hash 부분(키는 tx_uid 그대로) · Tron = txid", {k: (v.get("key"), v.get("tx")) for k, v in by.items()})
H_EVM = "0x" + "e1" * 32
docs.append({"kind": "tx", "key": "tx:eth:" + H_EVM, "grp": "tx:eth", "title": "tx evm", "sub": "", "body": "ETH", "date": "2023-11-14",
             "ts": 1_700_000_200, "chain": "eth", "etype": "transfer", "addr": EVM_A, "tx": H_EVM, "syms": ["ETH"], "chains": ["eth"]})
SPATH = os.path.join(T.TMP, "search_audit.db")
ix = si.Index(SPATH, sleep=lambda s9: None)
ix._insert(docs)


def keys_of(q):
    r = si.search(q, path=SPATH, budget_s=5)
    return sorted(i.get("id") for g in (r.get("groups") or []) for i in g.get("items") or [])


got = {q: keys_of(q) for q in (U_TR, "0x" + U_TR, U_TR.upper(), H_TON, H_EVM, H_EVM[2:])}
chk(got[U_TR] == ["tx:tron:" + U_TR] and got["0x" + U_TR] == ["tx:tron:" + U_TR] and got[U_TR.upper()] == ["tx:tron:" + U_TR],
    "A Tron txid(0x 없이 저장) = 64자리 hex · 0x 붙인 꼴 · 대문자로 찾음", got)
chk(got[H_TON] == ["tx:ton:" + U_TON], "A TON tx hash 로 찾음", got[H_TON])
got_i = {q: keys_of(q) for q in (TRON_D, TON_F, "0:" + "31" * 32)}
chk(got_i[TRON_D] == ["tx:tron:" + U_TR] and got_i[TON_F] == ["tx:ton:" + U_TON] and got_i["0:" + "31" * 32] == ["tx:ton:" + U_TON],
    "I 주소 검색: T… → Tron 지갑 tx · UQ…·0:… → TON 지갑 tx(원장 키로 대조)", got_i)
chk(si.parse_query(SOL_A)["exact"] == [("addr_or_tx", SOL_A)] and si.parse_query(EVM_A)["exact"] == [("addr", EVM_A)],
    "I 솔라나·EVM 주소 질의 해석 종전 그대로")
chk(got[H_EVM] == ["tx:eth:" + H_EVM] and got[H_EVM[2:]] == ["tx:eth:" + H_EVM], "A EVM 해시(0x 있든 없든) 종전 그대로", got)

import base64  # noqa: E402
from decimal import Decimal  # noqa: E402

import outflow_match as OM  # noqa: E402

SIG = "5" * 40 + "Ab" * 22
nt = {x: OM.norm_txid(x) for x in (U_TON, base64.b64encode(bytes.fromhex(H_TON)).decode(), base64.urlsafe_b64encode(bytes.fromhex("fb" * 32)).decode(),
                                   U_TR, "0X" + U_TR.upper(), SIG, "abc=", "")}
chk(nt[U_TON] == "0x" + H_TON and list(nt.values())[1] == "0x" + H_TON and list(nt.values())[2] == "0x" + "fb" * 32,
    "B TON tx_uid → 0x+hash · base64(표준·URL-safe) 32바이트 → 0x+hex", nt)
chk(nt[U_TR] == "0x" + U_TR and nt["0X" + U_TR.upper()] == "0x" + U_TR and nt[SIG] == SIG and nt["abc="] == "abc=" and nt[""] == "",
    "B 64자리 hex·솔라나 서명·짧은 base64·빈 값 = 종전 그대로", nt)
snd = [{"pid": 1, "txn": OM.norm_txid(U_TON), "chain": "ton", "dest": N.EXT["ton"], "sym": "TON", "qty": Decimal("7"), "ts": 1_700_000_100, "ok": True}]
dep = [{"ex": "okx", "uuid": "d1", "cur": "TON", "amt": Decimal("6.99"), "ts": 1_700_000_400, "txn": OM.norm_txid(base64.b64encode(bytes.fromhex(H_TON)).decode()),
        "origin_from": None}]
mt, _sg, pv = OM.match(snd, dep)
chk((mt.get(1) or {}).get("basis") == "txid" and (mt.get(1) or {}).get("uuid") == "d1" and pv.get(N.EXT["ton"]) == ("okx", "txid"),
    "B R1: 원장 TON 보냄 = 거래소 입금(base64 txid) txid 일치 · 입금주소 입증", (mt, pv))

import depaddr  # noqa: E402

DEP_T = ac.tron_display(N.EXT["tron"])
EVM_DEP = "0x" + "9e" * 20
json.dump({"v": 1, "exchanges": {}, "updated": 1, "records": [
    {"exchange": "binance", "currency": "USDT", "network": "TRX", "address": DEP_T, "tag": "", "chain": None, "sources": ["api"], "last_seen_api": 1},
    {"exchange": "binance", "currency": "USDT", "network": "ETH", "address": EVM_DEP, "tag": "", "chain": "eth", "sources": ["api"], "last_seen_api": 1}]},
    open(depaddr.store_path(), "w"))
h1 = depaddr.lookup("tron", N.EXT["tron"])
h2 = depaddr.lookup(None, DEP_T)
h3 = depaddr.lookup("eth", EVM_DEP)
chk(bool(h1) and h1.get("exchange") == "binance" and h1.get("match") == "exact" and not h1.get("tag_required"),
    "H Tron 원장 키(41…)로 거래소 입금주소(T…) 찾음 · 새 체인 질의 = exact", h1)
chk(bool(h2) and h2.get("match") == "address" and bool(h3) and h3.get("match") == "exact" and DEP_T in depaddr.hint_index(),
    "H 원문 T… 대조(체인 미지정 = address)·EVM exact·힌트 원문 키 종전 그대로", (h2, h3))
hm = OM.match([{"pid": 9, "txn": "0x" + "aa" * 32, "chain": "tron", "dest": N.EXT["tron"], "sym": "USDT", "qty": Decimal("50"), "ts": 1, "ok": True}], [],
              deposit_exchange=lambda ch9, a9: ((depaddr.lookup(ch9, a9) or {}).get("match") in ("exact", "family") or None)
              and depaddr.lookup(ch9, a9)["exchange"])
chk(hm[2].get(N.EXT["tron"]) == ("binance", "list"), "H 보낸 내역 R3: Tron 목적지 = 거래소 입금주소로 입증(web._deposit_exchange 와 같은 판정)", hm[2])

import shutil  # noqa: E402

import coverage_limits as CL  # noqa: E402
import health  # noqa: E402

os.makedirs(os.path.join(T.TMP, "seed", "coverage"), exist_ok=True)
for fn9 in ("api_limits.json", "token_sources.json"):
    if os.path.exists(os.path.join(T.ROOT, "seed", "coverage", fn9)):
        shutil.copy(os.path.join(T.ROOT, "seed", "coverage", fn9), os.path.join(T.TMP, "seed", "coverage", fn9))
t9 = CL.api_limits_table(T.ROOT) or {}
nx9 = [e for e in t9.get("chains") or [] if set(e.get("match") or ()) == set(reg.CHAINS)]
blob9 = json.dumps(nx9, ensure_ascii=False)
chk(len(nx9) == 1 and len(nx9[0]["rows"]) == 4 and all(set(r) == {"kind", "api", "bot", "miss", "todo"} for r in nx9[0]["rows"])
    and "0x" not in blob9 and all(n9 in blob9 for n9 in ("Tron", "Sui", "TON", "Bitcoin", "동결", "스테이킹", "깊은 재편", "스왑")),
    "L 정리표 새 체인 묶음 = 4줄 · 5칸 · 수집 한계(TRX 동결·Sui 스테이킹·BTC 깊은 재편·TON 스왑)", nx9)
bt9 = CL.build()
used9 = {e["id"]: e.get("used") for e in ((bt9.get("api_limits") or {}).get("chains") or [])}
chk(used9.get("nonevm") is True and used9.get("evm_explorer") is True, "L 새 체인 지갑 있음 = 그 묶음 '사용 중'(EVM 묶음 종전 그대로)", used9)
cfg_no = {k: v for k, v in cfg.items() if k != "chain_wallets"}
h0, h1 = health.settings(cfg_no), health.settings(cfg)
chk(h0["units"] == health.UNITS and h0["optional_units"] == health.OPTIONAL_UNITS, "L 헬스: 새 체인 지갑 없음 = 유닛 목록 종전 그대로", h0["units"])
chk(h1["units"] == health.UNITS + ["tj-ton", "tj-tron"] and {"tj-tron", "tj-ton"} <= set(h1["optional_units"]),
    "L 헬스: 지갑 있는 체인(tron·ton)만 tj-<체인> 선택 유닛(pm2 에 없으면 해당 없음)", (h1["units"], h1["optional_units"]))
chk({"tron", "sui", "ton", "btc"} <= set(health.RUNNER_KEYS), "L 헬스: pm2 없는 설치 = 러너 기록(runner_<체인>.json) 읽음")

T.finish()
