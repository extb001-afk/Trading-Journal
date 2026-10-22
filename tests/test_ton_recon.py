#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
from _ingest import check  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import config, paths  # noqa: E402
import core  # noqa: E402
import chain_event as ce  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402

DAY = 86400
NOW = int(time.time())
TON = 10 ** 9
A, X = F.K("31"), F.K("99")
M, MN, MF = F.K("a1"), F.K("a4"), F.K("a3")
WA, WN, WF = F.K("b1"), F.K("b4"), F.K("bf")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(A)}]
json.dump(cfg, open(CFG_PATH, "w"))

ch = F.Chain()
srv = F.Server(ch).start()
ch.tx(A, NOW - 200 * DAY, in_msg={"src": X, "val": 50 * TON}, tf=1000)
ch.tx(A, NOW - 10 * DAY, in_msg={"src": X, "val": 5 * TON}, tf=1000)
ch.tx(A, NOW - 9 * DAY, in_msg={"src": None}, outs=[{"dst": X, "val": TON, "fwd": 400}], tf=3000)
ch.add_jetton(A, WA, M, symbol="TKA", decimals="6")
ch.add_jetton(A, WF, MF, symbol="USDT", decimals="6", real=False)
ch.tx(WA, NOW - 8 * DAY, in_msg={"src": F.K("b9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(9_000_000, X)}, tf=0)
ch.jbal[WA] = 9_000_000
ch.jbal[WF] = 10 ** 15
W = SegmentWriter(INB)
st = cs.ChainState("ton")
ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
ad.page = 3
col = cw.Collector(ad, W, st, {A})
for _i in range(2):
    col.cycle()
c = core.Core(config.load_config())
c.conn.commit()
rd = SegmentReader(INB)
c._drain_stream("ton", rd, 1, 0)
c.conn.commit()

rb = tw.TonAdapter(config.load_config(), client=srv.client())
bal = rb.fetch_balances({A}, None, tokens={A: [M]})
v = ce.validate_balances(bal, "ton", {A})
check("V1 완전한 결과 · 공통 계약 통과", bal["_complete"] and v["ok"], (bal.get("_why"), v["why"]))
check("V1 네이티브 = 계정 잔고 · 제톤 = 검증된 지갑 잔고 · 가짜 지갑 잔고 안 셈",
      bal["per_wallet"][A] == {("native", None): ch.bal[A], ("token", M): 9_000_000}, bal["per_wallet"])
check("V1 메타(심볼·자릿수) · 경계 kind = account_lt", bal["_meta"].get(M) == ("TKA", 6) and bal["_boundary"]["kind"] == "account_lt", (bal["_meta"], bal["_boundary"]))

jt = ch.tx(WA, NOW - 100, in_msg={"src": F.K("b9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(1_000_000, X)}, tf=0)
ch.jbal[WA] += 1_000_000
b2 = rb.fetch_balances({A}, None, tokens={A: [M]})
check("V2 owner LT 그대로 · 제톤 지갑만 바뀜 = 보류(jetton_lt_ahead)", not b2["_complete"] and "jetton_lt_ahead" in b2["_why"]
      and not ce.validate_balances(b2, "ton", {A})["ok"], b2.get("_why"))
col.cycle()
check("V2 수집 뒤 = 다시 완전", rb.fetch_balances({A}, None, tokens={A: [M]})["_complete"])

wt = ch.tx(A, NOW - 50, in_msg={"src": X, "val": TON}, tf=1000)
b3 = rb.fetch_balances({A}, None)
check("V3 내 지갑 수집 전 tx = 보류(wallet_lt_ahead)", not b3["_complete"] and "wallet_lt_ahead" in b3["_why"], b3.get("_why"))
col.discover("latest")
b3b = rb.fetch_balances({A}, None)
check("V3 상세 대기 남음 = 보류(pending_details)", not b3b["_complete"] and "pending_details" in b3b["_why"], b3b.get("_why"))
col.cycle()
c._drain_stream("ton", rd, *[(r9["seg"], r9["off"]) for r9 in c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'")][0])
c.conn.commit()

ch.add_jetton(A, WN, MN, symbol="NEW", decimals="9")
ch.jbal[WN] = 5
b4 = rb.fetch_balances({A}, None)
check("V4 검증 안 된 새 제톤 지갑에 잔고 = 관측 못 함(0 아님) + 보류", not b4["_complete"] and MN in (b4["_unobserved"].get(A) or [])
      and ("token", MN) not in b4["per_wallet"][A], (b4.get("_why"), b4["_unobserved"]))
ch.jbal[WN] = 0
b4b = rb.fetch_balances({A}, None)
check("V4 잔고 0 인 미검증 지갑 = 무시(완전)", b4b["_complete"], b4b.get("_why"))
check("V4 가짜(검증 실패) 지갑 잔고 1e15 = 안 셈", ("token", MF) not in b4b["per_wallet"][A])

ZZ = F.K("a9")
b5 = rb.fetch_balances({A}, None, tokens={A: [M, ZZ]})
check("V5 원장 토큰인데 지갑 없음 = 0 칸", b5["per_wallet"][A].get(("token", ZZ)) == 0, b5["per_wallet"])
srv.ch.jw = [r for r in ch.jw if tw.akey(r["address"]) != WA]
b5b = rb.fetch_balances({A}, None, tokens={A: [M]})
check("V5 등록된 제톤 지갑이 목록에서 빠짐 = 관측 못 함(0 아님)", M in (b5b["_unobserved"].get(A) or []) and ("token", M) not in b5b["per_wallet"][A]
      and ce.validate_balances(b5b, "ton", {A})["usable"][A].get(("token", M)) is None, b5b["_unobserved"])
ch.add_jetton(A, WA, M, symbol="TKA", decimals="6")

srv.faults.append(("/accountStates", "500"))
e6 = T.safe(rb.fetch_balances, {A}, None)
check("V6 제공자 오류 = 예외(0 잔고 아님)", isinstance(e6, dict) and "Transient" in e6.get("_exc", ""), e6)
srv.faults.clear()


def openings():
    return {(r["symbol"], int(r["q"])) for r in c.conn.execute(
        "SELECT a.symbol, p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening' AND a.chain='ton'")}


def wsum(sym):
    r = c.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) s FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.location=? AND a.symbol=?",
                       (reg.make_location("ton", A), sym)).fetchone()
    return int(r["s"] or 0)


c.svc_recon._nonevm_adapters = {"ton": rb}
col.cycle()
c._drain_stream("ton", rd, *[(r9["seg"], r9["off"]) for r9 in c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'")][0])
c.conn.commit()
check("V7 준비(동기화 도장 + 백필 완료 + 대기 0)", c.svc_recon._scope_ready("ton"), st.status_view())
led_before = wsum("TON")
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
op = openings()
check("V7 대사 완료 도장", bool(c._meta_get("recon_done_ton")), op)
check("V7 기초 잔고 = 체인 잔고 − 원장(창 밖 옛 유입 50 TON − 수수료) · 제톤 기초 0",
      ("TON", ch.bal[A] - led_before) in op and ch.bal[A] - led_before == 50 * TON - 1000 and not any(s == "TKA" for s, _q in op), (op, ch.bal[A], led_before))
check("V7 지갑 칸 합 = 체인 잔고(TON · TKA)", wsum("TON") == ch.bal[A] and wsum("TKA") == ch.jbal[WA], (wsum("TON"), ch.bal[A], wsum("TKA"), ch.jbal[WA]))
ch.tx(WA, NOW - 10, in_msg={"src": F.K("b9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(2_000_000, X)}, tf=0)
ch.jbal[WA] += 2_000_000
c.conn.execute("DELETE FROM meta WHERE k='recon_done_ton'")
c.conn.commit()
c.svc_recon._last_recon = 0
op0 = openings()
c.svc_recon.recon_pass({"ton"})
check("V7 경합 중(제톤 지갑만 앞섬) 대사 = 보류 · 기초 잔고 그대로(유령 보정 없음)", openings() == op0 and not any(s == "TKA" for s, _q in openings()), openings())
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
