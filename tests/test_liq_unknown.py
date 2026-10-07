#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import json
import os
import time
import urllib.parse

os.environ["TJ_HEALTH"] = "0"
os.environ["TJ_TG_API"] = "http://127.0.0.1:9/never"
for k in ("TJ_TG_TOKEN", "TJ_TG_CHAT"):
    os.environ.pop(k, None)
S = os.path.join(H.TMP, "state")
CFG = os.path.join(H.TMP, "config.json")
with open(CFG, "w") as f:
    json.dump({}, f)
with open(os.path.join(H.TMP, ".env"), "w") as f:
    f.write("TJ_TG_TOKEN=000000:fake-test-token\nTJ_TG_CHAT=12345\n")
import common
import alert_prefs as AP
import liq_watch as LW


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:500])


def wcfg(d):
    common.atomic_write_json(CFG, d)
    time.sleep(0.01)


common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
T = [1_800_000_000.0]


class World:
    def __init__(self):
        self.bn_iso = []
        self.bn_loans = []
        self.bn_coll = {"BNB": {"marginCallLTV": "0.75", "liquidationLTV": "0.83"}}
        self.bn_pos = []
        self.mark = {}
        self.spot = {}
        self.okx_loans = []
        self.hl = {}
        self.tick_cost = 0.0
        self.calls = []


W = World()


def router(method, url, headers=None, body=None, timeout=6.0):
    u = urllib.parse.urlsplit(url)
    host, path, qs = u.hostname, u.path, dict(urllib.parse.parse_qsl(u.query))
    W.calls.append((T[0], host, path))
    if host == "api.binance.com":
        if path == "/sapi/v1/margin/account":
            return 200, {}, {"marginLevel": "999", "userAssets": []}
        if path == "/sapi/v1/margin/tradeCoeff":
            return 200, {}, {"normalBar": "1.5", "marginCallBar": "1.3", "forceLiquidationBar": "1.1"}
        if path == "/sapi/v1/margin/isolated/account":
            return 200, {}, {"assets": json.loads(json.dumps(W.bn_iso))}
        if path == "/sapi/v2/loan/flexible/ongoing/orders":
            return 200, {}, {"rows": json.loads(json.dumps(W.bn_loans)), "total": len(W.bn_loans)}
        if path == "/sapi/v2/loan/flexible/collateral/data":
            c = qs.get("collateralCoin")
            return 200, {}, {"rows": [dict(W.bn_coll[c], collateralCoin=c)] if c in W.bn_coll else []}
        if path == "/api/v3/ticker/price":
            rows = [{"symbol": s + "USDT", "price": str(p)} for (ex, s), p in W.spot.items() if ex == "binance"]
            if "symbols" in qs:
                want = json.loads(qs["symbols"])
                rows = [r for r in rows if r["symbol"] in want]
            return 200, {}, rows
    if host == "fapi.binance.com":
        if path == "/fapi/v3/positionRisk":
            return 200, {}, [{"symbol": p["sym"], "positionSide": "BOTH", "positionAmt": str(p["amt"]), "markPrice": str(W.mark.get(p["sym"], 0)),
                              "liquidationPrice": str(p["liq"])} for p in W.bn_pos]
        if path == "/fapi/v1/premiumIndex":
            s = qs.get("symbol")
            return 200, {}, {"symbol": s, "markPrice": str(W.mark.get(s, 0))}
    if host == "www.okx.com":
        if path == "/api/v5/finance/flexible-loan/loan-info":
            return 200, {}, {"code": "0", "data": json.loads(json.dumps(W.okx_loans))}
        if path == "/api/v5/account/positions":
            return 200, {}, {"code": "0", "data": []}
        if path == "/api/v5/market/ticker":
            s = qs.get("instId", "").split("-")[0]
            T[0] += W.tick_cost
            return 200, {}, {"code": "0", "data": [{"instId": qs.get("instId"), "last": str(W.spot.get(("okx", s), 1.0))}]}
    if host == "api.hyperliquid.xyz" and path == "/info":
        b = body or {}
        aps = [{"position": {"coin": c, "szi": str(szi), "positionValue": str(abs(szi) * mk), "liquidationPx": str(lq), "leverage": {"value": 3}}}
               for c, szi, mk, lq in W.hl.get(b.get("user"), [])]
        return 200, {}, {"assetPositions": aps, "marginSummary": {"accountValue": "1"}}
    raise LW.HttpErr(404, "not found")


LW.HTTP = router
BN = {"TJ_BINANCE_KEY": "k" * 16, "TJ_BINANCE_SECRET": "s" * 16}
OKX = {"TJ_OKX_KEY": "o" * 16, "TJ_OKX_SECRET": "p" * 16, "TJ_OKX_PASSPHRASE": "q" * 8}
TG = {"TJ_TG_TOKEN": "000:fake", "TJ_TG_CHAT": "1"}


def mk(env, rl=None):
    return LW.Watcher(env_fn=lambda: env, rl_map=rl if rl is not None else {}, clock=lambda: T[0], sync=True)


def run(w, sec, step=0.5):
    out = []
    end = T[0] + sec
    while T[0] < end - 1e-9:
        T[0] += step
        out += w.step(T[0])
    return out


def reset_state():
    for fn in (LW.STATE_NAME, AP.FAST_QUEUE, "leverage.json", "futures_lighter.json"):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass


def txt(xs):
    return [x["text"].split("\n")[0][:50] for x in xs]


r_unit = LW.estimate_ratio({"debt": [{"ccy": "USDT", "total": 100.0}]}, {}, T[0], 0.5)
r_unit2 = LW.estimate_ratio({"debt": [{"ccy": "USDT", "total": 100.0}], "collateral": [{"ccy": "USDC", "qty": 300.0}]}, {}, T[0], 0.5)
check("N1 estimate_ratio — 담보 목록 없음 = 신선 아님 · 양쪽 다 스테이블(알고 있음) = 신선", r_unit[2] is False and r_unit2[2] is True, (r_unit, r_unit2))
reset_state()
RL = {}
env = dict(TG, **BN)
w = mk(env, RL)
W.bn_iso = [{"symbol": "NIUSDT", "marginLevel": "1.15", "marginLevelStatus": "MARGIN_CALL", "liquidatePrice": "1900", "indexPrice": "2000",
             "baseAsset": {"asset": "NI", "borrowed": "0", "interest": "0"}, "quoteAsset": {"asset": "USDT", "borrowed": "1000", "interest": "1"}}]
got = run(w, 3)
check("N1 (준비) 격리마진 마진콜 → 🔴 1통", len([x for x in got if "NIUSDT" in x["text"]]) == 1, txt(got))
W.bn_iso[0].update(marginLevel="3", marginLevelStatus="NORMAL")
ts0 = (w.risk.get("bn_margin") or {}).get("ts")
n = 0
while (w.risk.get("bn_margin") or {}).get("ts") == ts0 and n < 200:
    got += run(w, 0.5)
    n += 1
RL["api.binance.com"] = T[0] + 3600
got2 = run(w, 115)
it9 = ((w.risk.get("bn_margin") or {}).get("recs") or {}).get("binance:margin_isolated:pair:NIUSDT") or {}
x9 = LW.risk_row(it9, T[0], {}, fast=True) if it9 else None
check("N1 정상(NORMAL) 스냅숏 한 장 뒤 조회가 막힘 = 115초 동안 ✅ 없음(담보를 모르면 거래소 값 15초 안만 해소 관찰)",
      not [x for x in got2 if x["text"].startswith("✅")] and x9 is not None and x9["pfresh"] is False,
      (txt(got2), x9 and x9.get("pfresh")))
RL.clear()
got3 = run(w, 190)
check("N1 조회가 이어져 NORMAL 이 두 번 넘게 확인되면 ✅ 1통", len([x for x in got3 if x["text"].startswith("✅") and "NIUSDT" in x["text"]]) == 1, txt(got3))
W.bn_iso = []
run(w, 65)

reset_state()
w = mk(dict(TG, **OKX))
W.okx_loans = [{"ordId": "n2", "collateralData": [{"ccy": c, "amt": "1"} for c in ("NA", "NB", "NC", "ND")],
                "loanData": [{"ccy": "USDT", "amt": "100"}], "curLTV": "0.5", "marginCallLTV": "0.8", "liqLTV": "0.9", "riskWarningData": {}}]
for c in ("NA", "NB", "NC", "ND"):
    W.spot[("okx", c)] = 100.0
W.tick_cost = 4.0
w.gate = (True, "")
t_start = T[0]
recs, pxs = w.fetch_risk("okx_loan", OKX, {})
W.tick_cost = 0.0
ts9 = {k: (v[1] if isinstance(v, tuple) else None) for k, v in pxs.items()}
check("N2 순차 조회 시세 시각 = 코인마다 요청 직전(첫 코인 = 시작 시각 · 마지막 시각으로 새것처럼 안 만듦)",
      ts9.get("NA") is not None and ts9["NA"] <= t_start + 0.01 and ts9.get("ND") is not None and ts9["ND"] <= t_start + 12.01, (t_start, ts9))
px0 = (recs.get("okx:loan:loan:n2") or {}).get("_px0") or {}
check("N2 추정 기준 시세(_px0) = 거래소 값 뒤 10초 안에 받은 코인만(12초 뒤 받은 ND 빠짐 → 추정 안 함)", "NA" in px0 and "ND" not in px0, sorted(px0))
try:
    w.px.clear()
    w.px["okx:NA"] = (101.0, T[0] + 50)
    w._put_px("okx:NA", (99.0, T[0]), T[0])
    put_ok = w.px["okx:NA"] == (101.0, T[0] + 50)
except AttributeError as e:
    put_ok = f"없음: {e}"
check("N2 더 새 시세(다른 일꾼이 먼저 받음)를 옛 값으로 안 덮음", put_ok is True, put_ok)
w.px.clear()
W.okx_loans = []

reset_state()
env = dict(TG, **BN)
w = mk(env)
W.bn_loans = [{"loanCoin": "USDT", "collateralCoin": "BNB", "totalDebt": "790", "collateralAmount": "10", "currentLTV": "0.79"}]
W.spot[("binance", "BNB")] = 100.0
got = run(w, 3)
n_alert = len([x for x in got if x["kind"] == "LOAN_RISK"])
levd = {"v": 1, "ts": int(T[0]), "cycle_sec": 600, "fresh_sec": 1320,
        "products": [{"ex": "binance", "product": "loan", "status": "ok", "measured_at": int(T[0])},
                     {"ex": "binance", "product": "futures_linear", "status": "ok", "measured_at": int(T[0])}],
        "items": [{"id": "binance:loan:loan:USDT-BNB", "ex": "binance", "product": "loan", "scope": "loan", "key": "USDT-BNB", "label": "바이낸스 담보대출 USDT←BNB",
                   "measured_at": int(T[0]), "stale": False,
                   "metrics": {"ltv": {"v": 0.79, "unit": "frac", "risk": "up", "call": 0.75, "liq": 0.83, "thr_src": "api:t", "src": "t"}}}]}
common.atomic_write_json(os.path.join(S, "leverage.json"), levd)
got = run(w, 3)
for k in ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"):
    env.pop(k)
got2 = run(w, 10)
check("N3 (준비) 빠른 조회 바이낸스 대출 🔴 1통", n_alert == 1 and not got, (n_alert, txt(got)))
check("N3 바이낸스 키를 지운 뒤 10초 — lev 파일 옛 대출 값으로 🔴 다시 안 만듦(0.5초마다 재생산 없음)", not got2, (len(got2), txt(got2)[:3]))
W.bn_loans = []
reset_state()
env = dict(TG, **BN)
w = mk(env)
W.bn_pos = [{"sym": "N3USDT", "amt": 1.0, "liq": 92.0}]
W.mark["N3USDT"] = 100.0
got = run(w, 8)
levd["items"] = [{"id": "binance:futures_linear:position:N3USDT:LONG", "ex": "binance", "product": "futures_linear", "scope": "position", "key": "N3USDT:LONG",
                  "label": "N3USDT 롱", "measured_at": int(T[0]), "stale": False, "metrics": {},
                  "position": {"symbol": "N3USDT", "side": "LONG", "qty": 1, "mark": 100.0, "liq": 92.0, "leverage": 5, "settle": "USDT"}}]
levd["products"] = [dict(p, measured_at=int(T[0])) for p in levd["products"]]
common.atomic_write_json(os.path.join(S, "leverage.json"), levd)
got += run(w, 3)
for k in ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"):
    env.pop(k)
got2 = run(w, 10)
check("N3 선물 — 키를 지운 뒤 lev 파일의 같은 포지션(바이낸스 USDⓈ-M)으로 🔴 다시 안 보냄", len([x for x in got if x["kind"] == "LIQ_NEAR"]) == 1 and not got2,
      (txt(got), txt(got2)))
W.bn_pos = []
os.remove(os.path.join(S, "leverage.json"))

reset_state()
ADDR = "0x" + "a1" * 20
wcfg({"perp_wallets": [{"dex": "hyperliquid", "address": ADDR, "label": "t"}]})
w = mk(dict(TG))
W.hl[ADDR] = [("N4", 1.0, 100.0, 93.0)]
got = run(w, 6)
with open(CFG, "w") as f:
    f.write('{"perp_wallets": [ 손상')
time.sleep(0.01)
got2 = run(w, 10)
kept = [k for k in w.st["fut"] if k.startswith("hyperliquid:N4")]
wcfg({"perp_wallets": [{"dex": "hyperliquid", "address": ADDR, "label": "t"}]})
got3 = run(w, 10)
check("N4 config.json 손상 = 마지막 정상 설정 유지(기억 유지) · 고친 뒤 같은 위험 재알림 없음",
      len(got) == 1 and not got2 and kept and not got3, (txt(got), txt(got2), kept, txt(got3)))
W.hl = {}
wcfg({})
run(w, 6)

reset_state()
A1, A2 = "0x" + "b2" * 20, "0x" + "c3" * 20


def lighter(pos_on, accts):
    common.atomic_write_json(os.path.join(S, "futures_lighter.json"), {
        "ts": int(T[0]), "positions": [{"symbol": "N5", "side": "LONG", "qty": 1, "mark": 100.0, "liq": 93.0, "acct": A2}] if pos_on else [],
        "accts": {a: {"ts": int(T[0])} for a in accts}})
    time.sleep(0.01)


wcfg({"perp_wallets": [{"dex": "lighter", "address": A1}, {"dex": "lighter", "address": A2}]})
w = mk(dict(TG))
lighter(True, [A1, A2])
got = run(w, 2)
wcfg({"perp_wallets": [{"dex": "lighter", "address": A1}]})
lighter(False, [A1])
got2 = run(w, 2)
left = [k for k in w.st["fut"] if k.startswith("lighter:")]
wcfg({"perp_wallets": [{"dex": "lighter", "address": A1}, {"dex": "lighter", "address": A2}]})
lighter(True, [A1, A2])
got3 = run(w, 2)
check("N5 설정에서 뺀 주소의 기억 = 조용히 잊음(✅ 없음) · 다시 넣고 위험하면 처음처럼 🔴 1통",
      len(got) == 1 and not got2 and not left and len(got3) == 1 and got3[0]["text"].startswith("🔴"), (txt(got), txt(got2), left, txt(got3)))
wcfg({})
os.remove(os.path.join(S, "futures_lighter.json"))

reset_state()
env = dict(TG, **BN)
w = mk(env)
W.bn_pos = [{"sym": "N6USDT", "amt": 1.0, "liq": 92.0}]
W.mark["N6USDT"] = 100.0
got = run(w, 8)
d0 = AP.preset_doc("rec")
d0["cats"]["liq"] = "off"
common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: d0})
time.sleep(0.01)
got2 = run(w, 5)
mem_off = sorted(w.st["fut"])
common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
time.sleep(0.01)
got3 = run(w, 8)
check("N6 '청산 근접'을 껐다 켜면 — 꺼진 동안 기억을 비우고, 다시 켠 뒤 지금 위험을 처음처럼 🔴 1통(꺼진 동안 풀렸다 다시 위험해져도 놓치지 않음)",
      len(got) == 1 and not got2 and not mem_off and len([x for x in got3 if x["text"].startswith("🔴")]) == 1, (txt(got), txt(got2), mem_off, txt(got3)))
W.bn_pos = []
run(w, 40)

reset_state()
env = dict(TG, **BN)
w = mk(env)
W.bn_pos = [{"sym": "N9USDT", "amt": 1.0, "liq": 92.0}]
W.mark["N9USDT"] = 100.0
got = run(w, 8)
env["TJ_BINANCE_KEY"] = "m" * 16
W.bn_pos = []
got2 = run(w, 40)
check("N9 거래소 키를 바꾸면 옛 계정 기억을 조용히 잊음 — 새 키 첫 목록에 없다고 '닫혀' ✅ 없음",
      len(got) == 1 and not got2 and not [k for k in w.st["fut"] if k.startswith("binance:N9")], (txt(got), txt(got2)))
W.bn_pos = [{"sym": "N9OLD", "amt": 1.0, "liq": 92.0}]
W.mark["N9OLD"] = 100.0
j9 = w._job("acct:binance")
j9.update(due=0, until=0)
w._submit("acct:binance", lambda: w.fetch_positions("binance", dict(env)), T[0])
j9["ksig"] = LW._key_sig(env, "binance") if hasattr(LW, "_key_sig") else None
env["TJ_BINANCE_KEY"] = "z" * 16
W.bn_pos = []
w.env()
w._collect(T[0])
check("N9 옛 키로 맡긴 조회 결과는 키를 바꾼 뒤 반영 안 함", "binance:N9OLD:LONG:" not in ((w.v.get("binance") or {}).get("pos") or {}), sorted((w.v.get("binance") or {}).get("pos") or {}))
run(w, 40)

W.bn_loans = [{"loanCoin": "USDT", "collateralCoin": "BNB", "totalDebt": "1", "collateralAmount": "10", "currentLTV": "0.1"}] * 100
w = mk(dict(TG, **BN))
w.gate = (True, "")
w.lim.take = lambda *a, **k: True
try:
    w.fetch_risk("bn_loan", BN, {})
    r7 = "정상(페이지 5까지만 · 뒤는 없음으로)"
except ValueError as e:
    r7 = "실패:" + str(e)[:40]
check("N7 바이낸스 대출 5페이지가 다 차면 = 조회 실패(뒤쪽 대출을 '갚음'으로 보지 않음)", r7.startswith("실패"), r7)
W.bn_loans = [{"loanCoin": "USDT", "collateralCoin": "BNB", "totalDebt": "1", "collateralAmount": "10", "currentLTV": "0.1"}]
w.thr["BNB"] = (None, None, T[0] - 700)
n0 = len([c for c in W.calls if c[2] == "/sapi/v2/loan/flexible/collateral/data"])
w.fetch_risk("bn_loan", BN, {})
n1 = len([c for c in W.calls if c[2] == "/sapi/v2/loan/flexible/collateral/data"])
check("N8 담보 임계를 못 받은 값(모름)은 6시간 굳히지 않고 10분 뒤 다시 받음", n1 == n0 + 1 and (w.thr.get("BNB") or (None,))[0] == 0.75, (n0, n1, w.thr.get("BNB")))
W.bn_loans = []

import alert_bot as ab

FQ = AP.FAST_QUEUE


def b_setup():
    for fn in ("alerts_web.jsonl", "pending_dm.jsonl", FQ, "tg_cursor.json", "alert_hold.json", "alert_stats.json"):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
    wcfg({})


def prefs_liq(on):
    d = AP.preset_doc("rec")
    if not on:
        d["cats"]["liq"] = "off"
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: d})
    time.sleep(0.01)


sent = []
o_send, o_sleep = ab.send, ab.time.sleep
ab.send = lambda tok, chat, text: sent.append(text.split("\n")[0]) or True
ab.time.sleep = lambda x: None
try:
    b_setup()
    now = int(time.time())
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": "🔴 꺼진 동안 줄\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
    cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
    st, hold = ab.load_stats(), ab.load_hold()
    ab._URG.update(token="t", chat="c", cursor=cursor, doc=AP.load(), conn=None, st=st, hold=hold, prefs_m=None)
    ab._URG["pos"].clear()
    prefs_liq(False)
    ab.urgent_pass()
    prefs_liq(True)
    ab.run_source(FQ, "t", "c", cursor, AP.load(), None, st, hold, {}, None)
    s1 = list(sent)
    skip1 = sum(int(((row or {}).get("liq") or {}).get("skip") or 0) for row in (st.get("days") or {}).values())
    b_setup2_cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
    sent.clear()
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": "🔴 꺼진 뒤 재시작\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
    hold2 = ab.load_hold()
    hold2["ids"][FQ] = []
    ab.save_hold(hold2)
    st2 = ab.load_stats()
    ab._URG.update(token="t", chat="c", cursor=b_setup2_cursor, doc=AP.load(), conn=None, st=st2, hold=ab.load_hold(), prefs_m=None)
    ab._URG["pos"].clear()
    prefs_liq(False)
    ab.urgent_pass()
    ab._URG["pos"].clear()
    prefs_liq(True)
    h3 = ab.load_hold()
    ab._URG.update(hold=h3)
    ab.urgent_pass()
    ab.run_source(FQ, "t", "c", b_setup2_cursor, AP.load(), None, ab.load_stats(), h3, {}, None)
    s2 = list(sent)
finally:
    ab.send, ab.time.sleep = o_send, o_sleep
check("B6 긴급 경로가 꺼진 동안 거른 줄 — 일반 판 전에 다시 켜도 안 보냄 · '꺼짐' 1번만 셈", "🔴 꺼진 동안 줄" not in s1 and skip1 == 1, (s1, skip1))
check("B6 꺼진 동안 거른 뒤 재시작(메모리 위치 잃음)해도 안 보냄", "🔴 꺼진 뒤 재시작" not in s2, s2)

sent = []
ab.send = lambda tok, chat, text: sent.append(text.split("\n")[0]) or True
ab.time.sleep = lambda x: None
o_save = ab.save_hold
try:
    b_setup()
    now = int(time.time())
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        for i in range(ab.READ_LINES_MAX):
            f.write(json.dumps({"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": f"🔴 앞줄 {i}\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": "🔴 청크 너머 줄\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
    cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
    st, hold = ab.load_stats(), ab.load_hold()
    ab._URG.update(token="", chat="", cursor=cursor, doc=AP.load(), conn=None, st=st, hold=hold, prefs_m=None)
    hold["_pend"] = {FQ: [1]}
    ab.save_hold = lambda h: False
    o_fso = ab._fast_send_ok
    calls9 = []

    def fso(kind, conn=None):
        calls9.append(1)
        return False
    ab._fast_send_ok = fso
    ab.run_source(FQ, "t", "c", cursor, AP.load(), None, st, hold, {}, None)
    ab._fast_send_ok = o_fso
    ab.save_hold = o_save
    far_off = os.path.getsize(os.path.join(S, FQ))
    marked = ab.held(hold, FQ, far_off)
finally:
    ab.send, ab.time.sleep, ab.save_hold = o_send, o_sleep, o_save
check("B7 청크 너머 앞 훑기에서 꺼진 긴급 줄 = '처리함'(다시 켜도 일반 경로가 안 보냄)", marked and "🔴 청크 너머 줄" not in sent, (marked, sent[:3], len(calls9)))

H.finish()
