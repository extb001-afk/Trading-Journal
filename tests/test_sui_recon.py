#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402
import _nonevm as N  # noqa: E402
import _suifake as F  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
try:
    import sui_watch as SW  # noqa: E402
except ImportError:
    import _wip_sui_watch as SW  # noqa: E402

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
USDC = "0x" + "a1" * 32 + "::usdc::USDC"
OLDT = "0x" + "d4" * 32 + "::old::OLD"
NEWT = "0x" + "e5" * 32 + "::newt::NEWT"
NOMETA = "0x" + "f6" * 32 + "::nm::NM"
ADDRB = "0x" + "17" * 32 + "::ab::AB"
BAD = "0x" + "28" * 32 + "::bad::BAD"
E9 = 10 ** 9
FEE = 2500

ch = F.Chain()
ch.page_cap = 3
ch.bal_cap = 2
ch.meta = {USDC: ("USDC", 6), OLDT: ("OLD", 2), NEWT: ("NEWT", 4), NOMETA: None, ADDRB: ("AB", 3), BAD: ("BAD", 0)}
srv, URL = F.start(ch)
TIP = ch.tip
ch.bal_min_ck = TIP - 3600
D_IN = ch.add(TIP - 30 * DAY, [(X, SUI, -4 * E9 - FEE), (A, SUI, 4 * E9)], sender=X)
D_TOK = ch.add(TIP - 20 * DAY, [(X, SUI, -FEE), (X, USDC, -5_000_000), (A, USDC, 5_000_000), (X, OLDT, -300), (A, OLDT, 300)], sender=X)
D_OUT = ch.add(TIP - 10 * DAY, [(A, SUI, -E9 - FEE), (X, SUI, E9), (A, OLDT, -300), (X, OLDT, 300)], sender=A)
SUI_BAL = 7 * E9
ch.bal[A] = [(SUI, SUI_BAL, SUI_BAL - 10, 10), (USDC, 6_500_000, 6_500_000, 0), (NEWT, 12345, 12345, None),
             (NOMETA, 777, 777, None), (ADDRB, 900, 0, 900), (BAD, 50, 30, 10)]
ch.bal[B] = []

CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}, {"chain": "sui", "address": B}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
ad = SW.make_adapter(cfg)
K = {t: reg.asset_key("sui", "token", t) for t in (USDC, OLDT, NEWT, NOMETA, ADDRB, BAD)}

ch.calls.clear()
bal = ad.fetch_balances({A, B}, None, tokens={A: sorted([K[USDC], K[OLDT]])})
pa = bal["per_wallet"][A]
chk = chain_event.validate_balances(bal, "sui", {A, B})
check("V1 경계 = 체크포인트 · 값 = 최신 · ts · 완주 · 계약 검사 통과", bal["_boundary"]["kind"] == "checkpoint" and bal["_boundary"]["value"] == str(TIP)
      and bal["_boundary"]["ts"] == ch.ts(TIP) and bal["_complete"] is False and bal.get("_why") == [chain_event.WHY_DEC_UNKNOWN, chain_event.WHY_SUM_MISMATCH]
      and chk["why"] == ["부분 결과(_complete 아님) — 자동 보정 보류 [token_decimals_unknown, token_sum_mismatch]"], (bal["_boundary"], chk["why"]))
check("V1 모든 쪽 같은 체크포인트(atCheckpoint 고정) · 쪽 2개씩 끝까지(6줄 = 3쪽)", {c9[1]["c"] for c9 in ch.calls if c9[0] == "SuiBal"} == {TIP}
      and sum(1 for c9 in ch.calls if c9[0] == "SuiBal" and c9[1]["a"] == A) == 3, [c9 for c9 in ch.calls if c9[0] == "SuiBal"])
check("V1 네이티브 SUI = totalBalance(코인 + 주소 잔고)", pa[("native", None)] == SUI_BAL, pa.get(("native", None)))
check("V2 주소 잔고만 있는 코인 = 900 · 코인+주소 ≠ 합계(BAD) = _unobserved", pa[("token", K[ADDRB])] == 900
      and K[BAD] in bal["_unobserved"].get(A, []) and ("token", K[BAD]) not in chk["usable"][A], bal["_unobserved"])
check("V3 원장 토큰 OLDT 완주 목록에 없음 = 0(관측) · USDC 6.5", pa[("token", K[OLDT])] == 0 and pa[("token", K[USDC])] == 6_500_000)
check("V3 자릿수 모르는 새 토큰 = 관측 안 함 · 자릿수 아는 새 토큰 = _meta(NEWT, 4)", K[NOMETA] in bal["_unobserved"].get(A, [])
      and ("token", K[NOMETA]) not in chk["usable"][A] and bal["_meta"].get(K[NEWT]) == ("NEWT", 4) and K[NOMETA] not in bal["_meta"], bal["_meta"])
check("V5 잔고 없는 지갑 B = 네이티브 0 관측(빈 목록 완주)", bal["per_wallet"][B] == {("native", None): 0})

ch.calls.clear()
ch.inject["SuiBal"] = [None, "range"]
ch.tip += 7
bal2 = ad.fetch_balances({A}, None, tokens={})
cks = [c9[1]["c"] for c9 in ch.calls if c9[0] == "SuiBal"]
check("V4 쪽 중간 범위 밖 = 새 경계(SuiCk 다시)로 처음부터 · 결과 완주", sum(1 for c9 in ch.calls if c9[0] == "SuiCk") == 2
      and bal2.get("_why") == [chain_event.WHY_DEC_UNKNOWN, chain_event.WHY_SUM_MISMATCH] and bal2["per_wallet"][A][("native", None)] == SUI_BAL and len(cks) == 2 + 3, (cks, ch.inject))
ch.inject["SuiBal"] = ["range"] * 3
try:
    ad.fetch_balances({A}, None, tokens={})
    r4 = "returned"
except cw.Transient as e:
    r4 = str(e)
check("V4 계속 범위 밖 = 예외(0 잔고 아님)", r4 != "returned" and "범위" in r4, r4)
for kind in ("http429", "http500", "gqlerr", "partial", "badjson"):
    ch.inject = {"SuiBal": [kind]}
    try:
        ad.fetch_balances({A}, None, tokens={})
        r5 = "returned"
    except cw.Transient as e:
        r5 = type(e).__name__
    check(f"V4 잔고 조회 {kind} = 예외(빈 결과·0 잔고 아님)", r5 != "returned", r5)
ch.inject = {}

w = SegmentWriter(os.path.join(paths.INBOX_DIR, "sui"))
st = cs.ChainState("sui")
col = SW.SuiCollector(SW.make_adapter(cfg), w, st, {A, B}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})
reg.FORCE_AVAILABLE.add("sui")
c = core.Core(config.load_config())
c.conn.commit()
c.svc_recon._nonevm_adapters = {"sui": SW.make_adapter(cfg)}
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("V6 수집기 상태 없음(준비 안 됨) = 대사 안 함", not c._meta_get("recon_done_sui"))
col.cycle()
sv = cs.ChainState("sui").status_view()
check("V5 거래 없는 지갑 B = 이력 끝 · 상세 완료 경계 · complete", sv.get(B, {}).get("complete") is True, sv.get(B))
rd = dict(c.chain_readers)["sui"]
c._drain_stream("sui", rd, 0, 0)
c.conn.commit()
check("V6 원장 3건", c.conn.execute("SELECT COUNT(*) FROM raw_txs WHERE chain='sui'").fetchone()[0] == 3)
check("V6 수집기 준비(동기화 도장·전 지갑 완료·대기 0)", c.svc_recon._scope_ready("sui"))
ch.tip += 20
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("V6 R3 후속: 잔고 있는 자릿수 모르는 새 코인(NOMETA 777) = 대사 보류(도장 없음 · 다음 주기 다시)", not c._meta_get("recon_done_sui"))
ch.bal[A] = [r9 if r9[0] != NOMETA else (NOMETA, 0, 0, None) for r9 in ch.bal[A]]
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("V6 S19 6.4: 합계 불일치 새 코인(BAD) 남음 = 여전히 보류(도장 없음 · 회복 뒤 다시)", not c._meta_get("recon_done_sui"))
ch.bal[A] = [r9 if r9[0] != BAD else (BAD, 50, 40, 10) for r9 in ch.bal[A]]
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
LA = reg.make_location("sui", A)


def op_of(sym):
    return sum(int(r["q"]) for r in c.conn.execute(
        "SELECT p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening' AND p.location=? AND a.symbol=?",
        (LA, sym)))


led_sui = 4 * E9 - E9 - FEE
check("V6 대사 완료 도장", bool(c._meta_get("recon_done_sui")))
check("V6 SUI 기초 잔고 = 경계 잔고 − 경계까지 원장(7 − 2.9999975)", op_of("SUI") == SUI_BAL - led_sui, (op_of("SUI"), SUI_BAL - led_sui))
check("V6 USDC 기초 잔고 = 6.5 − 5 = 1.5 · OLDT 0 − 0 = 레그 없음", op_of("USDC") == 1_500_000 and op_of("OLD") == 0, (op_of("USDC"), op_of("OLD")))
check("V6 자릿수 모르는 토큰 = 기초 잔고 없음 · 불일치 회복 토큰 = 기초 잔고 50(S19 6.4 — 영구 누락 없음)", op_of("NM") == 0 and op_of("BAD") == 50, op_of("BAD"))
pay = json.loads(c.conn.execute("SELECT payload FROM raw_observations WHERE obs_id='recon:sui'").fetchone()[0])
check("V6 관측 payload _block = 경계 체크포인트 · _source rpc", pay.get("_block") == ch.tip and pay.get("_source") == "rpc", {k: pay.get(k) for k in ("_block", "_source")})
tot = c.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=? AND a.symbol='SUI'",
                     (LA,)).fetchone()[0]
check("V6 지갑 SUI 칸 합 = 관측 잔고(7)", tot == SUI_BAL, tot)
reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
