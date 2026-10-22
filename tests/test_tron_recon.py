#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import bf_engine  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import chain_event as ce  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
import _tronfake as F  # noqa: E402
import tron_watch as TW  # noqa: E402

fake = F.FakeTron()
F.install_loop_open(bf_engine, T)
TW.TronAdapter.RATE_PAUSE = 0.05
bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"rate": 1000.0, "burst": 1000, "conc": 8}


def reset_gates():
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.clear()


reset_gates()
A, B = N.OWN["tron"]
X = N.EXT["tron"]
Z = "41" + "77" * 20
USDT = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
TK = N.TOK["tron"]
HINT = "41" + "b5" * 20
BAD = "41" + "bd" * 20
NOW = int(time.time() * 1000)
DAY = 86400_000
fake.head = [NOW // 3000 + 5, NOW - 60_000, "ab" * 32]
fake.tokmeta = {USDT: ("USDT", 6), TK: ("TKA", 18), HINT: ("HNT", 2)}
fake.accounts[A] = {"address": A, "balance": 12_000_000, "frozenV2": [{"amount": 2_000_000}, {"type": "ENERGY", "amount": 1_000_000}, {"type": "TRON_POWER"}],
                    "unfrozenV2": [{"unfreeze_amount": 500_000, "unfreeze_expire_time": 1}]}
fake.v1[A] = {"address": A, "trc20": [{F.T(USDT): "3000000"}, {F.T(HINT): "9"}]}
fake.tokbal.update({(USDT, A): 3_000_000, (HINT, A): 9, (TK, A): 0})
fake.revert.add(BAD)
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
cfg["nonevm"] = {"tron": {"api": fake.base, "rps": 1000, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
ad = TW.make_adapter(config.load_config())

bal = ad.fetch_balances({A}, None, tokens={A: [USDT, TK, BAD]})
pw = bal["per_wallet"].get(A) or {}
check("RB1 유동 TRX 12 · USDT 3 · 원장 토큰 0 도 넣음 · 힌트 토큰 9", pw == {("native", None): 12_000_000, ("token", USDT): 3_000_000, ("token", TK): 0,
                                                                      ("token", HINT): 9}, pw)
check("RB1 경계 = 확정 머리 높이·시각(height)", bal["_boundary"]["kind"] == "height" and int(bal["_boundary"]["value"]) == fake.head[0]
      and bal["_boundary"]["ts"] == fake.head[1] // 1000, bal["_boundary"])
check("RB1 힌트 토큰 메타(HNT·2자리) · 원장에 이미 있는 토큰은 메타를 다시 안 물음", bal["_meta"].get(HINT) == ("HNT", 2) and USDT not in bal["_meta"], bal["_meta"])
chk = ce.validate_balances(bal, "tron", {A})
check("RB1 대사 공통 반환 계약 통과(_complete)", chk["ok"] and bal["_complete"] is True, chk["why"])
check("RB2 잠긴 원금 = _locked(동결 3 · 해제 대기 0.5) — 유동 TRX 에 안 섞음", bal["_locked"].get(A) == {"frozen": "3000000", "unfreezing": "500000"}, bal["_locked"])
check("RB3 계약 거부 토큰 = _unobserved(0 아님)", bal["_unobserved"].get(A) == [BAD] and ("token", BAD) not in pw, bal["_unobserved"])
old_cap = TW.HINT_TOKEN_CAP
TW.HINT_TOKEN_CAP = 1
ZT = "41" + "2f" * 20
fake.v1[A]["trc20"] += [{F.T(TK): "5"}, {F.T(ZT): "0"}]
mark = len(fake.log)
bal_c = ad.fetch_balances({A}, None, tokens={A: []})
TW.HINT_TOKEN_CAP = old_cap
check("RB3 힌트 상한 넘는 토큰 = _unobserved(조회 안 한 칸은 0 아님)", len(bal_c["_unobserved"].get(A) or []) == 2
      and len([k for k in bal_c["per_wallet"][A] if k[0] == "token"]) == 1, bal_c["_unobserved"])
check("RB3 계정 목록 잔고 0 인 힌트(스팸 0 잔고) = 묻지 않음", ("token", ZT) not in bal_c["per_wallet"][A] and ZT not in (bal_c["_unobserved"].get(A) or [])
      and not any(ZT[2:] in (r or b"").decode() for (_m, _p, r, _h) in fake.log[mark:]), bal_c["_unobserved"])
fake.v1[A]["trc20"] = fake.v1[A]["trc20"][:2]

fake.tokbal[(USDT, Z)] = 4
bz = ad.fetch_balances({Z}, None, tokens={Z: [USDT]})
check("RB4 활성화 안 된 주소 = TRX 0 · 토큰은 balanceOf(4)", bz["per_wallet"][Z] == {("native", None): 0, ("token", USDT): 4} and bz["_complete"], bz["per_wallet"])
fake.v1[Z] = {"address": Z, "trc20": []}
try:
    ad.fetch_balances({Z}, None, tokens={})
    r4 = "결과"
except cw.Transient as e:
    r4 = str(e)
check("RB4 확정 계정 {} 인데 계정 목록엔 있음 = 다시(0 으로 안 봄)", r4 != "결과", r4)
fake.v1.pop(Z)

fake.call("%064x" % 0x51, NOW - 30_000, X, USDT, logs=[(USDT, A, X, 1)], list_value=0)
b5 = ad.fetch_balances({A}, None, tokens={A: [USDT]})
check("RB5 값 0 토큰 오염만 있으면 조용함(대사 진행)", b5["_complete"] is True, b5.get("_why"))
fake.transfer("%064x" % 0x52, NOW - 20_000, X, A, 1_000)
b5 = ad.fetch_balances({A}, None, tokens={A: [USDT]})
check("RB5 직전·읽는 중 내 거래 = _complete False(자동 보정 보류)", b5["_complete"] is False and not ce.validate_balances(b5, "tron", {A})["ok"], b5.get("_why"))
fake.txs = [t for t in fake.txs if t["txid"] not in ("%064x" % 0x51, "%064x" % 0x52)]

for name, sub, st9, body in (("머리 500", "getblock", 500, b"{}"), ("'Error' 응답", "getaccount", 200, b'{"Error": "request rate exceeded"}'),
                             ("잘린 본문", "triggerconstantcontract", 200, b'{"constant_result": ["00'),
                             ("계정 목록 형식", "/v1/accounts/", 200, b'{"data": null, "success": true}')):
    reset_gates()
    ad._pause_until = 0.0
    fake.inject.append((sub, st9, body))
    try:
        ad.fetch_balances({A}, None, tokens={A: [USDT]})
        r6 = "결과"
    except cw.Transient as e:
        r6 = "예외: " + str(e)[:60]
    check(f"RB6 {name} = 예외(0 잔고 결과 아님)", r6.startswith("예외"), r6)
fake.inject.clear()
reset_gates()
try:
    ad.fetch_balances({A}, {"kind": "height", "value": "10"}, tokens={})
    r6 = "결과"
except ValueError as e:
    r6 = str(e)
check("RB6 과거 경계 요청 = 거부(최신 잔고를 과거처럼 안 씀)", r6 != "결과", r6)

fake.transfer("%064x" % 0x61, NOW - 10 * DAY, X, A, 5_000_000)
fake.call("%064x" % 0x62, NOW - 9 * DAY, X, USDT, logs=[(USDT, X, A, 1_000_000)])
fake.transfer("%064x" % 0x63, NOW - 30_000, X, A, 2_000_000, blk=fake.head[0] + 3)
st = cs.ChainState("tron")
ad.state = st
col = cw.Collector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, "tron")), st, {A})
col.cycle()
check("RB7 수집 주기 끝 = 대사 준비(동기화·상세 완료·대기 0)", st.ready({A}), (st.d.get("synced_at"), st.d["status"].get(A), list(st.d["pending"])))
fake.txs = [t for t in fake.txs if t["txid"] != "%064x" % 0x63]
reg.FORCE_AVAILABLE.add("tron")
c = core.Core(config.load_config())
c.conn.commit()
rd = dict(c.chain_readers)["tron"]
c.svc_recon._recon_onchain("tron", {"per_wallet": {A: {("native", None): 1}}})
nat8 = c.conn.execute("SELECT symbol, decimals FROM assets WHERE chain='tron' AND kind='native'").fetchone()
check("RB8 대사가 먼저 만든 Tron 네이티브 자산 = 기호 TRX(레지스트리 · 'TRON' 아님) · 6자리", nat8 and nat8["symbol"] == "TRX" and nat8["decimals"] == 6,
      dict(nat8) if nat8 else None)
c.conn.commit()
c._drain_stream("tron", rd, 1, 0)
c.conn.commit()
check("RB7 core 어댑터 = Tron 수집기 make_adapter", isinstance(c.svc_recon._nonevm_adapter("tron"), TW.TronAdapter))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"tron"})
op = {(r["address"] or "native", int(r["q"])) for r in c.conn.execute(
    "SELECT a.address, p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening'")}
check("RB7 대사 완료 도장", bool(c._meta_get("recon_done_tron")))
check("RB7 기초 잔고 = 경계 잔고 − 경계까지 원장(TRX 12 − 5 = 7 · USDT 3 − 1 = 2 · 힌트 토큰 9 · 경계 뒤 +2 안 섞임)",
      op == {("native", 7_000_000), (USDT, 2_000_000), (HINT, 9)}, op)
pay = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id='recon:tron'").fetchone()[0])
check("RB7 관측 payload = 경계 블록(확정 머리)", pay.get("_block") == fake.head[0] and pay.get("_source") == "rpc", pay)
ha = c.conn.execute("SELECT decimals, symbol FROM assets WHERE chain='tron' AND address=?", (HINT,)).fetchone()
check("RB7 힌트 토큰 자산 = 메타(HNT 2자리)", ha and ha["symbol"] == "HNT" and ha["decimals"] == 2, dict(ha) if ha else None)
reg.FORCE_AVAILABLE.clear()
fake.close()
T.finish()
