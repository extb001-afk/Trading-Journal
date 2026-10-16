#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest
from _ingest import check
import _nonevm as N
import _suifake as F

import json
import os

import common
import core
import chain_event
import chain_registry as reg
import chain_state as cs
from inbox import SegmentWriter
import sui_watch as SW

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
NEWC = "0x" + "f7" * 32 + "::nc::NC"
E9 = 10 ** 9
ch = F.Chain()
ch.meta = {NEWC: ("NC", 6)}
srv, URL = F.start(ch)
TIP = ch.tip
ch.bal_min_ck = TIP - 3600
ch.add(TIP - 30 * DAY, [(X, SUI, -6 * E9 - 2500), (A, SUI, 3 * E9), (B, SUI, 3 * E9)], sender=X)
ch.bal[A] = [(SUI, 5 * E9, 5 * E9, 0), (NEWC, 1_000_000, 999_999, 0)]
ch.bal[B] = [(SUI, 4 * E9, 4 * E9, 0)]
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}, {"chain": "sui", "address": B}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = common.load_config()
KN = reg.asset_key("sui", "token", NEWC)

ad = SW.make_adapter(cfg)
bal = ad.fetch_balances({A, B}, None, tokens={})
v = chain_event.validate_balances(bal, "sui", {A, B})
check("SM1 새 코인 합계 불일치 = _unobserved · usable 에 없음", KN in (bal["_unobserved"].get(A) or []) and ("token", KN) not in v["usable"].get(A, {}),
      (bal["_unobserved"], v["usable"].get(A)))
check("SM1 대사 보류(_complete 아님 · 사유 token_sum_mismatch · 지갑별 보류 키 A 만)", bal["_complete"] is False and not v["ok"]
      and "token_sum_mismatch" in (bal.get("_why") or []) and (bal.get("_dec_unknown") or {}) == {A: [KN]},
      (bal["_complete"], bal.get("_why"), bal.get("_dec_unknown")))

w = SegmentWriter(os.path.join(common.INBOX_DIR, "sui"))
st = cs.ChainState("sui")
col = SW.SuiCollector(SW.make_adapter(cfg), w, st, {A, B}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})
col.cycle()
reg.FORCE_AVAILABLE.add("sui")
core.dm = lambda *a, **k: None
T.patch_moved("dm", core.dm)


def mk_core():
    c9 = core.Core(common.load_config())
    c9.conn.commit()
    c9._drain_stream("sui", dict(c9.chain_readers)["sui"], 0, 0)
    c9.conn.commit()
    c9._nonevm_adapters = {"sui": SW.make_adapter(cfg)}
    return c9


c = mk_core()
check("SM2 수집기 준비", c._scope_ready("sui"), cs.ChainState("sui").status_view())


def op(sym):
    return sum(int(r["q"]) for r in c.conn.execute(
        "SELECT p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening' AND a.chain='sui' AND a.symbol=?", (sym,)))


ch.tip += 5
c._last_recon = 0
c.recon_pass({"sui"})
check("SM2 합계 불일치 새 코인 = 체인 대사 보류(recon_done_sui 없음 · NC 기초 잔고 0)", not c._meta_get("recon_done_sui") and op("NC") == 0,
      (c._meta_get("recon_done_sui"), op("NC")))

out = T.safe(c._nonevm_fetch_plan("sui", [A, B], "new"))
check("SM3 Sui 지갑별 대사: A 만 _hold · B 는 독립 진행(per_wallet B)", isinstance(out, dict) and A in (out.get("_hold") or {})
      and set(out.get("per_wallet") or {}) == {B}, out if not isinstance(out, dict) else (out.get("_hold"), sorted(out.get("per_wallet") or {})))

ch.bal[A] = [(SUI, 5 * E9, 5 * E9, 0), (NEWC, 1_000_000, 1_000_000, 0)]
ch.tip += 5
c._last_recon = 0
c.recon_pass({"sui"})
check("SM4 회복 뒤 대사 = NC 기초 잔고 정확히 1,000,000 · 도장", bool(c._meta_get("recon_done_sui")) and op("NC") == 1_000_000,
      (c._meta_get("recon_done_sui"), op("NC")))
c.conn.close()
c = mk_core()
ch.tip += 5
c._last_recon = 0
c.recon_pass({"sui"})
c._last_recon = 0
c.recon_pass({"sui"})
check("SM4 core 재시작 · 재실행 멱등 = 여전히 1,000,000(이중 opening 없음)", op("NC") == 1_000_000, op("NC"))
reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
