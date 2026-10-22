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
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
import sui_watch as SW  # noqa: E402

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
NC = "0x" + "f8" * 32 + "::nc::NC"
E9 = 10 ** 9
FEE = 2500
ch = F.Chain()
ch.meta = {NC: ("NC", 6)}
srv, URL = F.start(ch)
TIP = ch.tip
ch.bal_min_ck = TIP - 3600
ch.add(TIP - 30 * DAY, [(X, SUI, -6 * E9 - FEE), (A, SUI, 3 * E9), (B, SUI, 3 * E9)], sender=X)
ch.add(TIP - 10 * DAY, [(X, SUI, -FEE), (X, NC, -1_000_000), (A, NC, 1_000_000)], sender=X)
ch.bal[A] = [(SUI, 5 * E9, 5 * E9, 0), (NC, 6_000_000, 5_999_999, 0)]
ch.bal[B] = [(SUI, 4 * E9, 4 * E9, 0)]
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}, {"chain": "sui", "address": B}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
KN = reg.asset_key("sui", "token", NC)

w = SegmentWriter(os.path.join(paths.INBOX_DIR, "sui"))
st = cs.ChainState("sui")
col = SW.SuiCollector(SW.make_adapter(cfg), w, st, {A, B}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})
col.cycle()
reg.FORCE_AVAILABLE.add("sui")
T.patch_moved("dm", lambda *a, **k: None)


def mk_core():
    c9 = core.Core(config.load_config())
    c9.conn.commit()
    c9._drain_stream("sui", dict(c9.chain_readers)["sui"], 0, 0)
    c9.conn.commit()
    c9.svc_recon._nonevm_adapters = {"sui": SW.make_adapter(cfg)}
    return c9


def q(c9, kind=None):
    sql = ("SELECT p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE a.chain='sui' AND a.symbol='NC'"
           " AND p.location=?" + (" AND p.source_kind=?" if kind else ""))
    return sum(int(r["q"]) for r in c9.conn.execute(sql, (f"wallet:sui:{A}",) + ((kind,) if kind else ())))


c = mk_core()
check("FO1 수집기 준비 · 창 안 +1 NC 기장(원장 tokens 에 NC) · opening 없음",
      c.svc_recon._scope_ready("sui") and q(c) == 1_000_000 and q(c, "opening") == 0, (c.svc_recon._scope_ready("sui"), q(c), q(c, "opening")))

ch.tip += 5
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("FO2 첫 대사 합계 불일치(원장에 있는 코인) = 체인 대사 보류(recon_done_sui 없음 · opening 0 — 1 로 완료 안 함)",
      not c._meta_get("recon_done_sui") and q(c, "opening") == 0 and q(c) == 1_000_000,
      (c._meta_get("recon_done_sui"), q(c, "opening"), q(c)))

out = T.safe(c.svc_recon._nonevm_fetch_plan("sui", [A, B], "new"))
check("FO3 Sui 지갑별 대사: 불일치 A 만 _hold · 정상 B 독립 진행(per_wallet B)", isinstance(out, dict) and KN in ((out.get("_hold") or {}).get(A) or [])
      and set(out.get("per_wallet") or {}) == {B}, out if not isinstance(out, dict) else (out.get("_hold"), sorted(out.get("per_wallet") or {})))

c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (f"wrecon_done:sui:{A}", "1"))
out = T.safe(c.svc_recon._nonevm_fetch_plan("sui", [A, B], "chain"))
check("FO4 이미 대사 끝난 지갑(wrecon_done) = 종전(원장에 있는 코인 불일치는 미관측 · 진행)", isinstance(out, dict) and not out.get("_hold")
      and KN in ((out.get("_unobs") or {}).get(A) or []) and set(out.get("per_wallet") or {}) == {A, B},
      out if not isinstance(out, dict) else (out.get("_hold"), out.get("_unobs"), sorted(out.get("per_wallet") or {})))
c.conn.execute("DELETE FROM meta WHERE k=?", (f"wrecon_done:sui:{A}",))
c.conn.commit()

ch.bal[A] = [(SUI, 5 * E9, 5 * E9, 0), (NC, 6_000_000, 6_000_000, 0)]
ch.tip += 5
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("FO5 회복 뒤 대사 = opening 정확히 5,000,000 + 거래 1,000,000 = 6,000,000 · 도장",
      bool(c._meta_get("recon_done_sui")) and q(c, "opening") == 5_000_000 and q(c) == 6_000_000,
      (c._meta_get("recon_done_sui"), q(c, "opening"), q(c)))
c.conn.close()
c = mk_core()
for _i in range(2):
    ch.tip += 5
    c.svc_recon._last_recon = 0
    c.svc_recon.recon_pass({"sui"})
check("FO5 core 재시작 · 재실행 멱등 = 여전히 6,000,000(opening 5,000,000 한 번)", q(c, "opening") == 5_000_000 and q(c) == 6_000_000,
      (q(c, "opening"), q(c)))
reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
