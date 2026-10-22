#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import acct_norm  # noqa: E402
import config, paths  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import web  # noqa: E402

chk = T.chk
DAY = 86400
NOW = int(time.time())
T1, T2 = NOW - 5 * DAY, NOW - 4 * DAY
c = core.Core(config.load_config())
PX = {"TKA": 2.5, "USDT": 1}
c.svc_exf._quote_usd = lambda q, ts: (__import__("decimal").Decimal(str(PX[q])) if q in PX else None)
c.px.fx_at = lambda ms: 1400.0
c.svc_exf._consume_exf_fills({"exchange": "binance", "fills": [
    {"id": "binance:div:1", "ts": T1 * 1000, "src": "income", "late": 1, "asset": "TKA", "base": "TKA", "amount": "40", "info": "Launchpool"},
    {"id": "binance:div:3", "ts": T1 * 1000, "src": "income", "late": 1, "asset": "USDT", "base": "USDT", "amount": "100", "info": "Simple Earn Flexible Interest"},
    {"id": "binance:div:2", "ts": T2 * 1000, "src": "income", "late": 1, "asset": "TKZ", "base": "TKZ", "amount": "7", "info": "Airdrop"}]})
c.conn.commit()
chk(c.conn.execute("SELECT count(*) FROM postings WHERE source_ns='binance:income' AND event='STAKE_REWARD'").fetchone()[0] == 3, "준비: 수입 행 3")


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    return (2.5, "ok") if "TKA" in str(spec).upper() else (None, "pending")


fake_lookup._tj_test_mock = True
histcurve.DAYCLOSE.lookup = fake_lookup
web.pricing._gj = lambda url, timeout=10.0: None
json.dump({"usd": {"TKA": 2.5}, "usd_ts": {"TKA": NOW}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(paths.state("spot.json"), "w"))
b = web.StateBuilder()
b.skip_gen_check = True
conn = dbm.open_db(paths.DB_PATH, readonly=True)
try:
    fb = b._build(conn)["fields"]
finally:
    conn.close()
pos = fb.get("positions") or []
st = next((p for p in pos if p.get("key") == "sstake"), {})
chk(abs(float(st.get("realized") or 0) - 200.0) < 0.01, "W1 보상 요약 카드 실현 = TKA 40 × $2.5 + USDT 이자 100 = $200(받은 시각 시가 = 소득)", st.get("realized"))
tax = [t for t in (fb.get("taxRows") or fb.get("tax_rows") or []) if t.get("ex") == "스테이킹 보상"]
chk(sorted((t.get("sym"), round(float(t.get("disp") or 0), 2)) for t in tax) == [("TKA", 100.0), ("USDT", 100.0)],
    "W1 세금 명세 = 받은 날 TKA·USDT '스테이킹 보상'(기타 소득) 각 $100(시가 없는 TKZ 는 없음)", tax)
rbd = fb.get("realizedByDate") or {}
dk = acct_norm.iso_day(T1)
chk(any(abs(float(v) - 200.0) < 0.01 for k, v in rbd.items() if dk.endswith(str(k)[-5:]) or str(k) == dk), "W1 받은 날 실현 +$200", {k: v for k, v in rbd.items()})
evs = [e for e in (fb.get("extraEvents") or []) + (fb.get("extraEventsHidden") or []) if e.get("sym") in ("TKA", "TKZ")]
chk(len(evs) == 2 and all("지급 내역(배당·에어드랍·런치풀·Earn 이자" in str(e.get("d")) and "MEV" not in str(e.get("d"))
                          and str(e.get("tx")) in ("", "—") and e.get("src") == "ex:binance" for e in evs),
    "W2 기록 줄 = '바이낸스 · 지급 내역(…)' · 거래 해시 없음 · 솔라나 'MEV 팁' 문구 아님", evs)
coins = {c9.get("sym"): c9 for c9 in (fb.get("coins") or [])}
ca, cz = coins.get("TKA") or {}, coins.get("TKZ") or {}
chk(ca.get("qty") == 40.0 and ca.get("kqty") == 40.0 and abs(float(ca.get("avg") or 0) - 2.5) < 1e-9,
    "W1 TKA 보유 40 = 원가 확인(평단 = 받은 시각 시가 $2.5)", {k: ca.get(k) for k in ("qty", "kqty", "avg")})
chk(cz.get("qty") == 7.0 and not cz.get("kqty") and "TKZ" not in {t.get("sym") for t in tax},
    "W3 시가 없는 지급(TKZ 7) = 원가 미확인 수량 · 소득(실현)·세금 줄 없음(추측 금지)", {k: cz.get(k) for k in ("qty", "kqty", "avg")})
T.finish()
