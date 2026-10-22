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

A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
TOK6 = "0x" + "a7" * 32 + "::six::SIX"
FEE = 2500
ch = F.Chain()
ch.meta = {TOK6: None}
srv, URL = F.start(ch)
TIP = ch.tip
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
INB = os.path.join(paths.INBOX_DIR, "sui")
w = SegmentWriter(INB)


def uids():
    out = []
    for f in sorted(os.listdir(INB)) if os.path.isdir(INB) else []:
        if f.endswith(".jsonl"):
            out += [json.loads(ln)["tx_uid"] for ln in open(os.path.join(INB, f)) if ln.strip()]
    return out


def col_for(st=None, owners=(A,)):
    return SW.SuiCollector(SW.make_adapter(cfg), w, st or cs.ChainState("sui"), set(owners),
                           page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})


def rerun_details(d, n=1, clear=True):
    for _i in range(n):
        st9 = cs.ChainState("sui")
        if d in st9.d["pending"]:
            st9.d["pending"][d]["next"] = 0
            st9.save()
        c9 = col_for(st9)
        if clear:
            c9.ad._cache.clear()
        c9.details("history")
        c9.details("latest")


reg.FORCE_AVAILABLE.add("sui")
c = core.Core(config.load_config())
c.conn.commit()
rd = dict(c.chain_readers)["sui"]


def drain():
    row = c.conn.execute("SELECT seg, off FROM inbox_offsets WHERE stream='sui'").fetchone()
    c._drain_stream("sui", rd, *((row["seg"], row["off"]) if row else (0, 0)))
    c.conn.commit()


D1 = ch.add(TIP - 86400, [(X, SUI, -FEE), (X, TOK6, -1_000_000), (A, TOK6, 1_000_000)], sender=X)
col = col_for()
col.cycle()
drain()
qn = c.conn.execute("SELECT p.qty_norm FROM positions p JOIN assets a ON a.group_id=p.group_id WHERE a.chain='sui' AND a.kind='token'").fetchall()
check("X1 자릿수 모르는 토큰 거래 = 방출 보류(대기 · core 에 자릿수 NULL 토큰 없음)", D1 not in uids() and D1 in cs.ChainState("sui").d["pending"]
      and not c.conn.execute("SELECT 1 FROM assets WHERE chain='sui' AND kind='token' AND decimals IS NULL").fetchone(),
      (D1 in uids(), [tuple(r) for r in qn]))
ch.meta[TOK6] = ("SIX", 6)
col.ad._meta.clear()
rerun_details(D1)
drain()
qn = c.conn.execute("SELECT p.qty_norm FROM positions p JOIN assets a ON a.group_id=p.group_id WHERE a.chain='sui' AND a.symbol='SIX'").fetchone()
check("X1 메타가 생기면 방출 · 원장 수량 = 1(자릿수 6 — 18 자리 0.000000000001 아님)", D1 in uids() and qn and qn[0] == "1", qn and qn[0])

for kind, chg in (("nogas", [(A, SUI, -FEE)]), ("nullowner", [(A, SUI, 7_000), (X, SUI, -7_000 - FEE)]), ("nopayer", [(A, SUI, -FEE)])):
    ch.tip += 100
    d3 = ch.add(ch.tip - 10, chg, sender=X if kind == "nullowner" else A)
    st3 = cs.ChainState("sui")
    col = col_for(st3)
    col.discover("latest")
    col.ad._cache.clear()
    ch.inject["SuiTx"] = [kind]
    col.details("latest")
    ch.inject.clear()
    check(f"X3 {kind} = 방출 보류(다시 예약 · 수수료 0·변화 없음으로 확정 안 함)", d3 not in uids() and d3 in cs.ChainState("sui").d["pending"], kind)
    rerun_details(d3)
    check(f"X3 {kind} 정상 응답이 오면 방출", d3 in uids(), kind)

def rec_of(d):
    for f in sorted(os.listdir(INB)):
        if f.endswith(".jsonl"):
            for ln in open(os.path.join(INB, f)):
                if ln.strip() and json.loads(ln)["tx_uid"] == d:
                    return json.loads(ln)
    return None


for kind in ("nogasinput", "nosponsorkey", "badsponsor"):
    ch.tip += 100
    d5 = ch.add(ch.tip - 10, [(A, SUI, -10 ** 9), (X, SUI, 10 ** 9 - FEE)], sender=A, sponsor=X)
    col = col_for(cs.ChainState("sui"))
    col.discover("latest")
    col.ad._cache.clear()
    ch.inject["SuiTx"] = [kind]
    col.details("latest")
    ch.inject.clear()
    r5 = rec_of(d5)
    check(f"X5 {kind}(보낸이 있음 · 수수료 있음) = 방출 보류(내 가스로 기장 안 함)", r5 is None and d5 in cs.ChainState("sui").d["pending"],
          r5 and r5.get("fees"))
    rerun_details(d5)
    r5 = rec_of(d5)
    check(f"X5 {kind} 정상 응답이 오면 방출 · 가스 = 스폰서(외부) 몫", r5 is not None
          and [(f["payer"], f["component"]) for f in r5["fees"]] == [(chain_event.EXTERNAL, "gas_sponsored")], r5 and r5.get("fees"))
ch.tip += 100
d5 = ch.add(ch.tip - 10, [(A, SUI, -10 ** 9 - FEE), (X, SUI, 10 ** 9)], sender=A)
col = col_for(cs.ChainState("sui"))
col.discover("latest")
col.ad._cache.clear()
ch.inject["SuiTx"] = ["nullsponsor"]
col.details("latest")
ch.inject.clear()
r5 = rec_of(d5)
check("X5 명시적 gasSponsor=null(스폰서 없음) = 보낸이(나)가 가스를 냄 · 바로 방출", r5 is not None
      and [(f["payer"], f["component"], f["amount_base"]) for f in r5["fees"]] == [(A, "gas", str(FEE))], r5 and r5.get("fees"))

ch.tip += 100
D2 = ch.add(ch.tip - 10, [(X, SUI, -100 * 10 ** 9 - FEE), (A, SUI, 100 * 10 ** 9)], sender=X)
col = col_for()
col.discover("latest")
for _i in range(cs.MAX_TRIES + 1):
    ch.inject["SuiTx"] = ["nulltx"]
    rerun_details(D2)
ch.inject.clear()
st2 = cs.ChainState("sui")
check("X2 상세 실패 상한 → gap(사유 내구)", any(g["id"] == D2 for g in st2.d["gaps"]) and D2 not in st2.d["pending"], st2.d["gaps"][-1:])
st2 = cs.ChainState("sui")
col = col_for(st2)
col.update_status()
st2.mark_synced()
st2.save()
st2 = cs.ChainState("sui")
check("X2 gap 남은 지갑 = 상세 완료 경계 없음 · 대사 준비 아님 · core 대사 스코프 준비 아님", (st2.d["status"].get(A) or {}).get("details_complete_through") is None
      and not st2.ready({A}) and not c.svc_recon._scope_ready("sui"), st2.d["status"].get(A))
st2.pending_upsert([(D2, {"stable_id": D2, "owner": A, "lane": "latest"})])
st2.save()
col = col_for(cs.ChainState("sui"))
col.cycle()
st2 = cs.ChainState("sui")
check("X2 같은 거래가 나중에 방출되면 gap 풀림 · 준비", D2 in uids() and (st2.d["status"].get(A) or {}).get("details_complete_through") is not None
      and st2.ready({A}), st2.d["status"].get(A))

ch.bal[A] = [(SUI, 100 * 10 ** 9, 80 * 10 ** 9, 10 * 10 ** 9)]
ad = SW.make_adapter(cfg)
try:
    bal = ad.fetch_balances({A}, None, tokens={})
    v4 = chain_event.validate_balances(bal, "sui", {A})
    r4 = ("returned", ("native", None) in (v4["usable"].get(A) or {}))
except cw.Transient as e:
    r4 = ("held", str(e)[:80])
check("X4 SUI 코인 + 주소 ≠ 합계 = 대사 결과 보류(그 합계를 쓰지 않음)", r4[0] == "held", r4)
ch.bal[A] = [(SUI, 90 * 10 ** 9, 80 * 10 ** 9, 10 * 10 ** 9)]
bal = ad.fetch_balances({A}, None, tokens={})
check("X4 일치하면 정상(90)", chain_event.validate_balances(bal, "sui", {A})["usable"][A][("native", None)] == 90 * 10 ** 9)

reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
