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
from inbox import SegmentWriter  # noqa: E402
import sui_watch as SW  # noqa: E402

DAY = 86400
A, B = N.OWN["sui"]
X = N.EXT["sui"]
SUI = F.SUI_T
NOMETA = "0x" + "f6" * 32 + "::nm::NM"
E9 = 10 ** 9
ch = F.Chain()
ch.meta = {NOMETA: None}
srv, URL = F.start(ch)
TIP = ch.tip
ch.bal_min_ck = TIP - 3600
ch.add(TIP - 30 * DAY, [(X, SUI, -6 * E9 - 2500), (A, SUI, 3 * E9), (B, SUI, 3 * E9)], sender=X)
ch.bal[A] = [(SUI, 5 * E9, 5 * E9, 0), (NOMETA, 777, 777, None)]
ch.bal[B] = [(SUI, 4 * E9, 4 * E9, 0)]
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "sui", "address": A}, {"chain": "sui", "address": B}]
cfg["nonevm"] = {"sui": {"graphql_url": URL, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
cfg = config.load_config()
KN = reg.asset_key("sui", "token", NOMETA)

ad = SW.make_adapter(cfg)
bal = ad.fetch_balances({A, B}, None, tokens={})
v = chain_event.validate_balances(bal, "sui", {A, B})
check("S1 새 코인 잔고 > 0 + 자릿수 모름 = _unobserved · usable 에 없음", KN in (bal["_unobserved"].get(A) or []) and ("token", KN) not in v["usable"].get(A, {}),
      (bal["_unobserved"], v["usable"].get(A)))
check("S1 대사 보류(_complete 아님 · 사유 · 지갑별 _dec_unknown)", bal["_complete"] is False and not v["ok"]
      and "token_decimals_unknown" in (bal.get("_why") or []) and (bal.get("_dec_unknown") or {}).get(A) == [KN],
      (bal["_complete"], bal.get("_why"), bal.get("_dec_unknown")))
b2 = ad.fetch_balances({A}, None, tokens={A: [KN]})
check("S2 원장에 이미 있는 코인 + 자릿수 모름 = 보류 아님(수량 대조)", b2["_complete"] is True and b2["per_wallet"][A].get(("token", KN)) == 777, (b2["_complete"], b2.get("_why")))

w = SegmentWriter(os.path.join(paths.INBOX_DIR, "sui"))
st = cs.ChainState("sui")
col = SW.SuiCollector(SW.make_adapter(cfg), w, st, {A, B}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})
col.cycle()
reg.FORCE_AVAILABLE.add("sui")
c = core.Core(config.load_config())
c.conn.commit()
T.patch_moved("dm", lambda *a, **k: None)
c._drain_stream("sui", dict(c.chain_readers)["sui"], 0, 0)
c.conn.commit()
check("S3 수집기 준비", c.svc_recon._scope_ready("sui"), cs.ChainState("sui").status_view())
cad = SW.make_adapter(cfg)
c.svc_recon._nonevm_adapters = {"sui": cad}


def op(sym):
    return sum(int(r["q"]) for r in c.conn.execute(
        "SELECT p.qty_base AS q FROM postings p JOIN assets a ON a.asset_id=p.asset_id WHERE p.source_kind='opening' AND a.chain='sui' AND a.symbol=?", (sym,)))


ch.tip += 5
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
check("S3 자릿수 모르는 새 코인 있음 = 체인 대사 보류(recon_done_sui 없음 · 기초 잔고 0 · 자산 없음)", not c._meta_get("recon_done_sui")
      and op("SUI") == 0 and c.conn.execute("SELECT COUNT(*) FROM assets WHERE chain='sui' AND kind='token'").fetchone()[0] == 0,
      (c._meta_get("recon_done_sui"), op("SUI")))

out = T.safe(c.svc_recon._nonevm_fetch_plan("sui", [A, B], "new"))
check("S4 Sui 지갑별 대사: A 만 _hold · B 는 독립 진행(per_wallet B)", isinstance(out, dict) and A in (out.get("_hold") or {})
      and set(out.get("per_wallet") or {}) == {B}, out if not isinstance(out, dict) else (out.get("_hold"), sorted(out.get("per_wallet") or {})))
ch.bal[B] = [(SUI, 4 * E9, 4 * E9, 0), (NOMETA, 5, 5, None)]
out2 = T.safe(c.svc_recon._nonevm_fetch_plan("sui", [A, B], "new"))
check("S4 두 지갑 다 자릿수 모르는 코인 = 지갑별 대사 보류(예외 · 0 잔고 아님)", isinstance(out2, dict) and "_exc" in out2, out2)
ch.bal[B] = [(SUI, 4 * E9, 4 * E9, 0)]

ch.meta[NOMETA] = ("NM", 2)
SW.META_NONE_TTL = 0
c.svc_recon._last_recon = 0
c.svc_recon.recon_pass({"sui"})
dec = c.conn.execute("SELECT decimals FROM assets WHERE chain='sui' AND kind='token'").fetchone()
check("S3 메타 확인 뒤 = 대사 진행 · NM 기초 잔고 777 · 자릿수 2 · 도장", bool(c._meta_get("recon_done_sui")) and op("NM") == 777
      and dec is not None and dec["decimals"] == 2, (c._meta_get("recon_done_sui"), op("NM"), dict(dec) if dec else None))
reg.FORCE_AVAILABLE.clear()
srv.shutdown()
T.finish()
