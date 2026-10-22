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
A, B, X = F.K("31"), F.K("32"), F.K("99")
MS, WS = F.K("a7"), F.K("b7")
MN, WN = F.K("a8"), F.K("b8")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
tw.META_RETRY_SEC = 0
T.patch_moved("dm", lambda *a, **k: None)
INVALID = {"valid": False, "type": "jetton_masters", "extra": {}}

md_bad = {"0:AA": {"is_indexed": True, "token_info": [INVALID]}}
m1 = tw._meta_of({"jetton_content": {"uri": "ipfs://x"}}, md_bad)
m2 = tw._meta_of({"jetton_content": {"uri": "ipfs://x"}}, {})
m3 = tw._meta_of({"jetton_content": {"uri": "ipfs://x"}}, {"0:AA": {"token_info": [INVALID, {"valid": True, "type": "jetton_masters", "symbol": "Q", "extra": {}}]}})
m4 = tw._meta_of({"jetton_content": {"decimals": "6", "uri": "ipfs://x"}}, md_bad)
m5 = tw._meta_of({"jetton_content": {"uri": "ipfs://x"}}, {"0:AA": {"token_info": [{"valid": False, "type": "nft_items", "extra": {}}]}})
check("SM1 명시 무효(valid:false 행만) = invalid · 자릿수 None", m1.get("invalid") is True and m1["decimals"] is None, m1)
check("SM1 메타 없음(색인 전) = invalid 아님(종전 보류)", not m2.get("invalid") and m2["decimals"] is None, m2)
check("SM1 유효 행 있음 · 체인 위 자릿수 있음 · 다른 종류 행 = invalid 아님", not m3.get("invalid") and m3["decimals"] == 9
      and not m4.get("invalid") and m4["decimals"] == 6 and not m5.get("invalid"), (m3, m4, m5))

cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(w)} for w in (A, B)]
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
ch = F.Chain()
srv = F.Server(ch).start()
for owner, old, new in ((A, 1_000_000, 1), (B, 100, 2)):
    ch.tx(owner, NOW - 400 * DAY, in_msg={"src": X, "val": old * TON}, tf=0)
    ch.tx(owner, NOW - 2 * DAY, in_msg={"src": X, "val": new * TON}, tf=0)
ch.add_jetton(A, WS, MS, symbol=None, decimals=None, onchain=False)
ch.masters[MS] = ({"uri": "ipfs://synthetic-spam"}, INVALID)
ch.tx(WS, NOW - 400 * DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(1000, X)}, tf=0)
ch.jbal[WS] = 1000
W = SegmentWriter(INB)
st = cs.ChainState("ton")
ad = tw.TonAdapter(cfg, client=srv.client(), state=st)
col = cw.Collector(ad, W, st, {A, B})
for _i in range(3):
    col.cycle()
c = core.Core(cfg)
c.conn.commit()
rb = tw.TonAdapter(cfg, client=srv.client())
c.svc_recon._nonevm_adapters = {"ton": rb}


def drain():
    rd = SegmentReader(INB)
    for _i in range(50):
        row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        seg, off = (row["seg"], row["off"]) if row else (1, 0)
        c._drain_stream("ton", rd, seg, off)
        row2 = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='ton'").fetchone()
        if row2 and row and (row2["seg"], row2["off"]) == (seg, off):
            break
    c.conn.commit()


def native(w):
    return sum(int(r[0]) for r in c.conn.execute(
        "SELECT p.qty_base FROM postings p JOIN assets a USING(asset_id) WHERE a.chain='ton' AND a.kind='native' AND p.location=?",
        (reg.make_location("ton", w),)))


def tok_assets():
    return c.conn.execute("SELECT count(*) FROM assets WHERE chain='ton' AND kind='token'").fetchone()[0]


drain()
check("SM2 수집 준비(대기 0 · gap 0) · 메타 invalid 저장", st.ready({A, B}) and not st.d["gaps"] and not st.d["pending"]
      and st.d["ton"]["meta"].get(MS, {}).get("invalid") is True, (st.d["gaps"], st.d["ton"]["meta"].get(MS)))
bal = rb.fetch_balances({A, B}, None)
chk = ce.validate_balances(bal, "ton", {A, B})
check("SM2 경로 A: _complete True · 스팸은 A 의 _unobserved 에만(보류 사유 아님) · 공통 계약 통과",
      bal["_complete"] is True and "jetton_decimals_unknown" not in bal["_why"] and bal["_unobserved"].get(A) == [MS]
      and not bal["_unobserved"].get(B) and chk["ok"], (bal["_complete"], bal["_why"], bal["_unobserved"], chk["why"]))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
check("SM2 체인 대사 완료 · 두 지갑 네이티브 = 체인 잔고(A 1,000,001 · B 102) · 스팸 토큰 자산 없음",
      bool(c._meta_get("recon_done_ton")) and native(A) == ch.bal[A] == 1_000_001 * TON and native(B) == ch.bal[B] == 102 * TON
      and tok_assets() == 0, (c._meta_get("recon_done_ton"), native(A), ch.bal[A], native(B), ch.bal[B], tok_assets()))

sp = ch.tx(WS, NOW - DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(7, X)}, tf=0)
ch.jbal[WS] = 1007
SID = tw.tx_uid(tw.akey(sp["account"]), sp["lt"], sp["_hex"])
for _i in range(cs.MAX_TRIES + 3):
    col.cycle()
    for p in st.d["pending"].values():
        p["next"] = 0
check("SM3 경로 B: 창 안 스팸 수신 = 재예약·gap 없이 기장(그 제톤 레그만 뺌) · 준비 유지",
      st.emitted(SID) and not st.d["gaps"] and not st.d["pending"] and st.ready({A, B}), (st.d["gaps"], list(st.d["pending"])))
drain()
r9 = c.conn.execute("SELECT snapshot FROM raw_txs WHERE chain='ton' AND txhash=?", (SID,)).fetchone()
snap = json.loads(r9[0]) if r9 else {}
check("SM3 레코드: 토큰 레그 없음 · 사유 jetton_meta_invalid_skipped · 원장 네이티브 그대로 · 토큰 자산 0",
      r9 is not None and not [d for d in snap.get("deltas") or [] if (d.get("asset") or {}).get("kind") == "token"]
      and "jetton_meta_invalid_skipped" in ((snap.get("completeness") or {}).get("reasons") or [])
      and native(A) == ch.bal[A] and tok_assets() == 0, (r9 is not None, (snap.get("completeness") or {}).get("reasons"), native(A), tok_assets()))
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
check("SM3 다음 대사 주기 뒤에도 네이티브 = 체인 잔고", native(A) == ch.bal[A] and native(B) == ch.bal[B], (native(A), native(B)))

ch.add_jetton(B, WN, MN, symbol=None, decimals=None, onchain=False)
ch.tx(WN, NOW - 400 * DAY, in_msg={"src": F.K("c8"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5, X)}, tf=0)
ch.jbal[WN] = 5
for _i in range(3):
    col.cycle()
bal4 = rb.fetch_balances({B}, None)
check("SM4 메타 없는 제톤 잔고 = jetton_decimals_unknown 보류(_complete 아님 · 종전 그대로)",
      not st.d["ton"]["meta"].get(MN, {}).get("invalid") and bal4["_complete"] is False and "jetton_decimals_unknown" in bal4["_why"],
      (st.d["ton"]["meta"].get(MN), bal4["_complete"], bal4["_why"]))
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
