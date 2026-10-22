#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401
import _nonevm as N  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import bf_engine  # noqa: E402
import config, paths  # noqa: E402
import address_codec as ac  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state as cs  # noqa: E402
from inbox import SegmentWriter  # noqa: E402
import _tronfake as TF  # noqa: E402
import _suifake as SF  # noqa: E402
import tron_watch as TW  # noqa: E402
import sui_watch as SW  # noqa: E402


def chk(msg, ok, extra=None):
    T.chk(ok, msg, extra)


A, _B = N.OWN["tron"]
X = N.EXT["tron"]
SPAM = "41" + "e7" * 20
fake = TF.FakeTron()
TF.install_loop_open(bf_engine, T)
fake.tokmeta = {SPAM: ("SPM", None)}
NOW = int(time.time() * 1000)
DAY = 86400_000
fake.transfer("%064x" % 1, NOW - 3 * DAY, X, A, 5_000_000)
fake.call("%064x" % 2, NOW - 2 * DAY, X, SPAM, logs=[(SPAM, X, A, 10 ** 9)])
fake.accounts[A] = {"address": A, "balance": 5_000_000}
fake.v1[A] = {"address": ac.tron_display(A), "trc20": [{ac.tron_display(SPAM): str(10 ** 9)}]}
fake.tokbal[(SPAM, A)] = 10 ** 9
CFG_PATH = os.path.join(T.TMP, "config.json")
cfg = json.load(open(CFG_PATH))
cfg["chain_wallets"] = [{"chain": "tron", "address": ac.tron_display(A)}]
cfg["nonevm"] = {"tron": {"api": fake.base, "rps": 1000, "retries": 1}}
json.dump(cfg, open(CFG_PATH, "w"))
ad = TW.make_adapter(config.load_config())
ad.state = cs.ChainState("tron")
r1 = T.safe(ad.fetch_and_normalize, {"stable_id": "%064x" % 2}, {A})
chk("N1 반대: 첫 확인(1번) = 종전 보류(자릿수 모름 레그 — 수집기가 다시 예약)", isinstance(r1, dict) and chain_event.unknown_decimals(r1) != [], r1)
ad._meta_neg[SPAM] = 0
r2 = T.safe(ad.fetch_and_normalize, {"stable_id": "%064x" % 2}, {A})
chk("N1 2번째(확정적 없음) = 그 레그·이동 증거 빼고 사유 token_decimals_invalid_skipped · 보류 아님",
    isinstance(r2, dict) and not chain_event.unknown_decimals(r2) and not any((d.get("asset") or {}).get("kind") == "token" for d in r2.get("deltas") or [])
    and not any((m.get("asset") or {}).get("kind") == "token" for m in r2.get("movements") or [])
    and "token_decimals_invalid_skipped" in (r2.get("completeness") or {}).get("reasons", []), r2)
r3 = T.safe(ad.fetch_and_normalize, {"stable_id": "%064x" % 1}, {A})
chk("N1 반대: 정상 TRX 거래 = 종전 그대로(사유 없음)", isinstance(r3, dict) and not (r3.get("completeness") or {}).get("reasons")
    and any(int(d.get("delta_base") or 0) == 5_000_000 for d in r3.get("deltas") or []), r3)
b2 = T.safe(ad.fetch_balances, {A}, None, tokens={A: []})
chk("N2 Tron 대사: 확정적 없음 토큰(힌트·잔고 > 0) = 그 칸만 관측 밖 · 보류 아님",
    isinstance(b2, dict) and "_exc" not in b2 and b2.get("_complete") is True and SPAM in (b2.get("_unobserved") or {}).get(A, []), b2)
ad3 = TW.make_adapter(config.load_config())
ad3.state = cs.ChainState("tron")
b3 = T.safe(ad3.fetch_balances, {A}, None, tokens={A: []})
chk("N2 반대: 처음 본(1번) 자릿수 모름 = 종전 보류(_complete 아님)", isinstance(b3, dict) and b3.get("_complete") is False
    and SPAM in (b3.get("_unobserved") or {}).get(A, []), b3)
ad4 = TW.make_adapter(config.load_config())
ad4._call = lambda *a, **k: {}
r4 = T.safe(ad4.token_meta, SPAM)
r5 = T.safe(ad4.token_meta, SPAM)
chk("N1 반대: 노드 이상 응답 = 다시 조회(Transient) · 확정적 없음으로 안 셈", all("Transient" in str((x or {}).get("_exc")) for x in (r4, r5))
    and not ad4._dec_bad.get(SPAM), (r4, ad4._dec_bad))
fake.close()

SA, _SB = N.OWN["sui"]
SX = N.EXT["sui"]
NOMETA = "0x" + "f6" * 32 + "::nm::NM"
sch = SF.Chain()
sch.meta = {NOMETA: None}
ssrv, SURL = SF.start(sch)
STIP = sch.tip
sch.bal_min_ck = STIP - 3600
sch.add(STIP - 2 * 86400, [(SX, SF.SUI_T, -3 * 10 ** 9 - 2500), (SA, SF.SUI_T, 3 * 10 ** 9)], sender=SX)
sch.add(STIP - 86400, [(SX, NOMETA, -50), (SA, NOMETA, 50), (SX, SF.SUI_T, -2500)], sender=SX)
sch.bal[SA] = [(SF.SUI_T, 3 * 10 ** 9, 3 * 10 ** 9, 0), (NOMETA, 50, 50, None)]
cfg9 = json.load(open(CFG_PATH))
cfg9["chain_wallets"] = [{"chain": "sui", "address": SA}]
cfg9["nonevm"] = {"sui": {"graphql_url": SURL, "retries": 1}}
json.dump(cfg9, open(CFG_PATH, "w"))
KN = reg.asset_key("sui", "token", NOMETA)
sad = SW.make_adapter(config.load_config())
sb1 = T.safe(sad.fetch_balances, {SA}, None, tokens={})
chk("N3 Sui 반대: coinMetadata null 1번 = 종전 보류(_complete 아님 · token_decimals_unknown)",
    isinstance(sb1, dict) and sb1.get("_complete") is False and "token_decimals_unknown" in (sb1.get("_why") or []), sb1)
for k9, v9 in list(sad._meta.items()):
    sad._meta[k9] = (v9[0], v9[1], 0)
sb2 = T.safe(sad.fetch_balances, {SA}, None, tokens={})
chk("N3 Sui 대사: null 2번(확정적 없음) = 그 칸만 관측 밖 · 보류 아님", isinstance(sb2, dict) and sb2.get("_complete") is True
    and KN in (sb2.get("_unobserved") or {}).get(SA, []) and not (sb2.get("_dec_unknown") or {}), sb2)
sw9 = SegmentWriter(os.path.join(paths.INBOX_DIR, "sui"))
sst = cs.ChainState("sui")
scol = SW.SuiCollector(sad, sw9, sst, {SA}, page_budget={"latest": 5, "history": 20}, detail_budget={"latest": 100, "history": 500})
for _i in range(3):
    scol.cycle()
d9 = os.path.join(paths.INBOX_DIR, "sui")
srecs = [json.loads(ln) for f in sorted(os.listdir(d9)) if f.endswith(".jsonl") for ln in open(os.path.join(d9, f)) if ln.strip()] if os.path.isdir(d9) else []
nm9 = [x for x in srecs if "token_decimals_invalid_skipped" in ((x.get("completeness") or {}).get("reasons") or [])]
chk("N3 Sui 기장: 메타 확정적 없음 코인 레그만 빼고 방출(사유) · 다른 거래 그대로 · gap 0",
    len(srecs) == 2 and len(nm9) == 1 and not any((d.get("asset") or {}).get("kind") == "token" for x in srecs for d in x.get("deltas") or [])
    and not sst.unresolved_gaps(), [(x.get("deltas"), x.get("completeness")) for x in srecs])
ssrv.shutdown()
T.finish()
