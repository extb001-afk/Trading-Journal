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
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
import chain_watch as cw  # noqa: E402
import address_codec as ac  # noqa: E402
from inbox import SegmentWriter, SegmentReader  # noqa: E402
import ton_watch as tw  # noqa: E402
import _ton_fake as F  # noqa: E402


def S(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:   # noqa: BLE001
        return f"예외:{type(e).__name__}"


DAY = 86400
NOW = int(time.time())
TON = 10 ** 9
X = F.K("99")
CFG_PATH = os.path.join(T.TMP, "config.json")
INB = os.path.join(paths.INBOX_DIR, "ton")
reg.FORCE_AVAILABLE.add("ton")
tw.META_RETRY_SEC = 0


def set_wallets(*keys):
    cfg = json.load(open(CFG_PATH))
    cfg["chain_wallets"] = [{"chain": "ton", "address": ac.ton_friendly(k)} for k in keys]
    json.dump(cfg, open(CFG_PATH, "w"))
    return config.load_config()


ch = F.Chain()
srv = F.Server(ch).start()


def uid_of(t):
    return tw.tx_uid(tw.akey(t["account"]), t["lt"], t["_hex"])


def due_now(st):
    for p in st.d["pending"].values():
        p["next"] = 0


D, WD, MD = F.K("43"), F.K("c3"), F.K("e3")
ch.tx(D, NOW - 3 * DAY, in_msg={"src": X, "val": TON}, tf=1000)
ch.add_jetton(D, WD, MD, symbol=None, decimals=None, onchain=False)
dt = ch.tx(WD, NOW - 2 * DAY, in_msg={"src": F.K("c9"), "val": 1, "op": tw.OP_INTERNAL_TRANSFER, "body": F.body_internal(5_000_000, X)}, tf=0)
ch.jbal[WD] = 5_000_000
SID = uid_of(dt)
set_wallets(D)
W = SegmentWriter(INB)
st = cs.ChainState("ton")
ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
ad.page = 3
col = cw.Collector(ad, W, st, {D}, page_budget={"latest": 10, "history": 20}, detail_budget={"latest": 200, "history": 500})
col.cycle()
check("TG1 첫 주기: 자릿수 모르는 제톤 수신 = 대기(기장 보류)", SID in st.d["pending"] and not st.emitted(SID), list(st.d["pending"]))
for _i in range(cs.MAX_TRIES + 3):
    if SID not in st.d["pending"]:
        break
    due_now(st)
    col.cycle()
col.cycle()
check("TG1 실제 MAX_TRIES 뒤 gap 1 · 대기 0 · 동기화 도장", [g["id"] for g in st.d["gaps"]] == [SID] and not st.d["pending"] and st.d.get("synced_at"),
      (st.d["gaps"], list(st.d["pending"])))
ch.masters[MD] = ({"decimals": "6"}, {"valid": True, "type": "jetton_masters", "symbol": "DD", "extra": {}})
col.cycle()
col.cycle()
check("TG1 메타 회복(자릿수 6) · 그래도 gap 거래는 원장에 없음(자동 재기장 없음)", (st.d.get("ton") or {}).get("meta", {}).get(MD, {}).get("decimals") == 6
      and not st.emitted(SID), (st.d.get("ton") or {}).get("meta", {}).get(MD))

c = core.Core(config.load_config())
c.conn.commit()
rb = tw.TonAdapter(config.load_config(), client=srv.client())
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


def jet(kind):
    r = c.conn.execute("SELECT SUM(CAST(p.qty_base AS INTEGER)) s FROM postings p JOIN assets a ON a.asset_id=p.asset_id"
                       " WHERE a.chain='ton' AND a.kind='token' AND lower(a.address)=lower(?) AND p.source_kind" + ("='opening'" if kind == "opening" else "!='opening'"),
                       (MD,)).fetchone()
    return int(r["s"] or 0)


drain()
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
st = cs.ChainState("ton")
check("TG1 test_ton_gap_recon_hold: gap 미해소 = 대사 보류 — 제톤 5,000,000 이 opening 으로 흡수되지 않음", jet("opening") == 0, jet("opening"))
check("TG1 recon_done_ton 없음 · ready 거짓 · 화면 complete 거짓", not c._meta_get("recon_done_ton") and not st.ready({D})
      and st.status_view()[D]["complete"] is False, (c._meta_get("recon_done_ton"), st.ready({D})))

g = [x for x in st.d["gaps"] if x["id"] == SID][-1]
st.pending_upsert([(SID, g["ref"])])
st.d["pending"][SID]["next"] = 0
st.save()
ad = tw.TonAdapter(config.load_config(), client=srv.client(), state=st)
ad.page = 3
col = cw.Collector(ad, W, st, {D}, page_budget={"latest": 10, "history": 20}, detail_budget={"latest": 200, "history": 500})
col.cycle()
drain()
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"ton"})
st = cs.ChainState("ton")
check("TG1 복구 뒤 기장 = chain_tx +5,000,000 · 제톤 opening 0 · gap 이력 1건 유지 · 완료 도장",
      jet("chain") == 5_000_000 and jet("opening") == 0 and len(st.d["gaps"]) == 1 and st.ready({D}) and bool(c._meta_get("recon_done_ton")),
      (jet("chain"), jet("opening"), st.d["gaps"], c._meta_get("recon_done_ton")))

jw0 = list(ch.jw)
ch.jw = [r for r in ch.jw if tw.akey(r["address"]) != WD]
b3 = rb.fetch_balances({D}, None, tokens={D: [MD]})
check("TG3 등록된 제톤 지갑이 목록에서 빠짐 = _unobserved + 대사 보류(jetton_wallet_missing · 완료 도장으로 영구 누락 없음)",
      MD in (b3["_unobserved"].get(D) or []) and b3["_complete"] is False and "jetton_wallet_missing" in (b3.get("_why") or []),
      (b3["_unobserved"], b3["_complete"], b3.get("_why")))
ch.jw = jw0
check("TG3 목록 회복 = 다시 완전", rb.fetch_balances({D}, None, tokens={D: [MD]})["_complete"] is True)

A1, B1 = F.K("41"), F.K("42")
ch.tx(A1, NOW - 9 * DAY, in_msg={"src": X, "val": 10 * TON}, tf=1000)
p1 = ch.tx(A1, NOW - 5 * DAY, in_msg={"src": None}, outs=[{"dst": B1, "val": 3 * TON, "fwd": 400}], tf=3000)
p2 = ch.recv(p1, 0, B1, NOW - 5 * DAY + 5, tf=900)
set_wallets(D, A1, B1)
SD2 = os.path.join(T.TMP, "sd2")
os.makedirs(SD2, exist_ok=True)
st2 = cs.ChainState("ton", SD2)
ad2 = tw.TonAdapter(config.load_config(), client=srv.client(), state=st2)
ad2.page = 3
_lk = ad2._lookup
ad2._lookup = lambda h, d: None if d == "out" else _lk(h, d)
col2 = cw.Collector(ad2, SegmentWriter(os.path.join(T.TMP, "inb2")), st2, {A1, B1},
                    page_budget={"latest": 10, "history": 20}, detail_budget={"latest": 200, "history": 500})
for _i in range(cs.MAX_TRIES + 4):
    col2.cycle()
    due_now(st2)
col2.cycle()
R1, R2 = uid_of(p1), uid_of(p2)
check("TG2 받는 쪽 sid = gap · 보낸 쪽 묶음(뿌리 uid)으로 기장 · 방출 uid 에 받는 쪽 sid 없음(_rebase 오인 없음)",
      R2 in [x["id"] for x in st2.d["gaps"]] and st2.emitted(R1) and not st2.emitted(R2), ([x["id"] for x in st2.d["gaps"]], st2.emitted(R1)))
check("TG2 묶음이 담은 받는 쪽 tx = 해결 관계로 해소 → 미해소 gap 0 · 대사 준비(영구 보류 없음)",
      S(lambda: st2.unresolved_gaps()) == [] and st2.ready({A1, B1}) and ((st2.em.get("res") or {}).get(R2) or {}).get("u") == R1,
      (S(lambda: st2.unresolved_gaps()), st2.em.get("res")))
srv.stop()
reg.FORCE_AVAILABLE.clear()
T.finish()
