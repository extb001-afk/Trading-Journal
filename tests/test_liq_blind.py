#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import json
import os
import time
import urllib.parse

for k in ("TJ_TG_TOKEN", "TJ_TG_CHAT"):
    os.environ.pop(k, None)
S = os.path.join(H.TMP, "state")
CFG = os.path.join(H.TMP, "config.json")
import common
import alert_prefs as AP
import liq_watch as LW
import health as HH

PRH = getattr(LW, "PERM_RETRY_HELD", 300)


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:700])


def wcfg(d):
    common.atomic_write_json(CFG, d)
    time.sleep(0.01)


def wprefs(doc):
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: doc})
    time.sleep(0.01)


wcfg({})
wprefs(AP.preset_doc("rec"))
T = [1_800_000_000.0]
MODE = {"pos": "ok", "loan": "ok"}
MARK = {}
POS = []
LOANS = []
SPOT = {}
CALLS = []


def router(method, url, headers=None, body=None, timeout=6.0):
    u = urllib.parse.urlsplit(url)
    host, path, qs = u.hostname, u.path, dict(urllib.parse.parse_qsl(u.query))
    CALLS.append((T[0], host, path))
    if host == "fapi.binance.com":
        if path == "/fapi/v3/positionRisk":
            if MODE["pos"] == "401":
                raise LW.HttpErr(401, '{"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}')
            if MODE["pos"] == "timeout":
                raise TimeoutError("timed out")
            return 200, {}, [{"symbol": p["sym"], "positionSide": "BOTH", "positionAmt": str(p["amt"]),
                              "markPrice": str(MARK[p["sym"]]), "liquidationPrice": str(p["liq"])} for p in POS]
        if path == "/fapi/v1/premiumIndex":
            s = qs.get("symbol")
            return 200, {}, {"symbol": s, "markPrice": str(MARK.get(s, 0))}
    if host == "api.binance.com":
        if path == "/sapi/v1/margin/account":
            return 200, {}, {"marginLevel": "999", "userAssets": []}
        if path == "/sapi/v1/margin/isolated/account":
            return 200, {}, {"assets": []}
        if path == "/sapi/v2/loan/flexible/ongoing/orders":
            return 200, {}, {"rows": [], "total": 0}
    if host == "www.okx.com":
        if path == "/api/v5/account/positions":
            return 200, {}, {"code": "0", "data": []}
        if path == "/api/v5/finance/flexible-loan/loan-info":
            if MODE["loan"] == "401":
                raise LW.HttpErr(401, '{"code":"50113","msg":"Invalid Sign"}')
            rows = []
            for r in LOANS:
                r = dict(r)
                ltv0, px0, c = r.pop("_ref")
                r["curLTV"] = str(ltv0 * px0 / SPOT[c])
                rows.append(r)
            return 200, {}, {"code": "0", "data": rows}
        if path == "/api/v5/market/ticker":
            c = qs.get("instId", "").split("-")[0]
            return 200, {}, {"code": "0", "data": [{"instId": qs.get("instId"), "last": str(SPOT[c])}]}
    raise LW.HttpErr(404, "not found")


LW.HTTP = router
ENV = {"TJ_TG_TOKEN": "000:fake", "TJ_TG_CHAT": "1", "TJ_BINANCE_KEY": "k" * 16, "TJ_BINANCE_SECRET": "s" * 16}


def reset():
    for fn in (LW.STATE_NAME, AP.FAST_QUEUE):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    MODE.update(pos="ok", loan="ok")
    POS[:] = []
    LOANS[:] = []
    MARK.clear()
    SPOT.clear()


def mk(env=None):
    return LW.Watcher(env_fn=lambda: dict(env if env is not None else ENV), rl_map={}, clock=lambda: T[0], sync=True)


def run(w, sec, step=1.0):
    out = []
    end = T[0] + sec
    while T[0] < end - 1e-9:
        T[0] += step
        out += w.step(T[0])
    return out


def heads(xs):
    return [x["text"].split("\n")[0][:70] for x in xs]


def blind(xs):
    return [x for x in xs if (x.get("lw") or {}).get("g") == "blind"]


def near(xs):
    return [x for x in xs if (x.get("lw") or {}).get("g") == "fut"]


def long_at(dist_pct, liq=50000.0):
    return liq / (1 - dist_pct / 100)


for mode, lbl in (("401", "401 한 번"), ("timeout", "타임아웃 지속")):
    reset()
    POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
    MARK["BTCUSDT"] = 60000.0
    w = mk()
    a0 = run(w, 60)
    MODE["pos"] = mode
    a1 = run(w, 660)
    ok_at = float(w.v["binance"].get("pos_ts") or 0)
    MARK["BTCUSDT"] = 52000.0
    a2 = run(w, 120, step=2.0)
    MARK["BTCUSDT"] = 50000.0
    a3 = run(w, 120, step=2.0)
    n2, n3 = near(a2), near(a3)
    check(f"P1 [{lbl}] 11분째 못 본 포지션이 3.8% → 🔴 위험 알림(마지막 청산가 + 신선한 마크가격) · '청산가는 N분 전 값 · 포지션 조회 실패 중' 꼬리표",
          not near(a0 + a1) and len(n2) == 1 and "청산가까지 3.8% 남았어요" in n2[0]["text"] and "분 전 값 · 포지션 조회 실패 중" in n2[0]["text"],
          (heads(a0 + a1), [x["text"] for x in n2]))
    check(f"P2 [{lbl}] 청산가 도달 → '닿았거나 지났어요' 1통 더", len(n3) == 1 and "닿았거나 지났어요" in n3[0]["text"], heads(a3))
    b1 = blind(a1)
    check(f"N1 [{lbl}] 들고 있는(위험 구간 밖) 곳을 5분 넘게 못 봄 → 🔴 '청산 감시가 바이낸스 선물을 못 보고 있어요' 1통(마지막 정상·마지막으로 본 위험도·원인)",
          len(b1) == 1 and b1[0]["text"].startswith("🔴 청산 감시가 바이낸스 선물을 못 보고 있어요\n") and "마지막 정상 " in b1[0]["text"]
          and "마지막으로 본 위험도: BTCUSDT 롱 청산가까지 16.7%(알림 기준 10%)" in b1[0]["text"]
          and ("API 키 권한 오류" if mode == "401" else "연결 실패·시간 초과") in b1[0]["text"] and b1[0]["kind"] == "LIQ_NEAR",
          [x["text"] for x in b1] or heads(a1))
    t_b = (b1[0]["ts"] - ok_at) if b1 else None
    check(f"N1 [{lbl}] 못 봄 알림 = 마지막 정상 조회 뒤 5분(+2초 안)", t_b is not None and 300 <= t_b <= 302, t_b)
    b2 = blind(a2 + a3)
    check(f"N2 [{lbl}] 못 보는 동안 위험 구간에 들어감 → 긴급 문장으로 1번 더('마지막에 청산 위험 구간이었어요(긴급)')",
          len(b2) == 1 and "마지막에 청산 위험 구간이었어요(긴급)" in b2[0]["text"] and "청산가까지 3.8%" in b2[0]["text"], [x["text"] for x in b2])
    if mode == "401":
        j9 = w.jobs["acct:binance"]
        check("K1 들고 있는 곳의 권한 오류 = 5분 뒤 다시(6시간 쉬지 않음)", 0 < j9["until"] - T[0] <= PRH, j9["until"] - T[0])
        pr = [c for c in CALLS if c[2] == "/fapi/v3/positionRisk" and c[0] > T[0] - 900]
        check("K1 … 15분에 다시 시도 2~4번(하루 288번 이하)", 2 <= len(pr) <= 4, len(pr))
    a4 = run(w, 3700, step=10.0)
    b4 = blind(a4)
    check(f"N3 [{lbl}] 위험 구간에서 계속 못 봄 → 1시간 뒤 '아직 … 못 보고 있어요' 다시 1통", len(b4) == 1 and "아직 바이낸스 선물을 못 보고 있어요" in b4[0]["text"],
          [x["text"][:80] for x in b4])
    MODE["pos"] = "ok"
    POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 45000.0}]
    a5 = run(w, 320, step=2.0)
    b5 = blind(a5)
    check(f"N4 [{lbl}] 다시 보이면 ✅ '다시 보고 있어요' 1통(무음 · resolved)", len(b5) == 1 and b5[0]["text"].startswith("✅ 청산 감시가 바이낸스 선물을 다시 보고 있어요")
          and b5[0].get("resolved") and "동안 못 봤어요" in b5[0]["text"], [x["text"] for x in b5])
    sf = common.read_json(os.path.join(S, LW.STATE_NAME), {})
    v9 = ((sf.get("status") or {}).get("venues") or {}).get("binance") or {}
    check(f"N4 [{lbl}] 복구 뒤 상태 파일 bl 0 · 못 봄 기억 없음", v9.get("bl") == 0 and not (sf.get("blind") or {}), (v9, sf.get("blind")))

reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(8)
w = mk()
a0 = run(w, 30)
MODE["pos"] = "timeout"
ok_at = float(w.v["binance"].get("pos_ts") or 0)
a1 = run(w, ok_at + 119 - T[0])
a2 = run(w, 20)
check("N5 마지막에 위험 구간(8% · 알림 보냄)인 포지션을 못 봄 → 2분 전엔 0 · 2분 넘으면 긴급 1통(5분 안 기다림)",
      len(near(a0)) == 1 and not blind(a1) and len(blind(a2)) == 1 and "(긴급)" in blind(a2)[0]["text"]
      and 120 <= blind(a2)[0]["ts"] - ok_at <= 122, (heads(a0), heads(a1), heads(a2)))
sf = common.read_json(os.path.join(S, LW.STATE_NAME), {})
v9 = ((sf.get("status") or {}).get("venues") or {}).get("binance") or {}
check("N5 상태 파일 = bl 3 · since(마지막 정상) · 곳 이름 · 마지막으로 본 위험도", v9.get("bl") == 3 and v9.get("since") and v9.get("where") == "바이낸스 선물"
      and "BTCUSDT 롱 청산가까지 8.0%" in str(v9.get("worst")), v9)
w.save(T[0], force=True)
w2 = mk()
a3 = run(w2, 360)
check("N6 재시작 뒤 장애가 6분 이어짐 — 같은 '못 보고 있어요' 다시 0통(기억 파일) · 기억 유지", not blind(a3) and "f:binance" in (w2.st.get("blind") or {}),
      (heads(a3), w2.st.get("blind")))
os.remove(os.path.join(S, LW.STATE_NAME))
w3 = mk()
a3 = run(w3, 360)
check("N6 기억 파일이 없어도(긴급 줄 기록으로 되살림) 장애 6분 — 다시 0통", not blind(a3) and "f:binance" in (w3.st.get("blind") or {}),
      (heads(a3), w3.st.get("blind")))
w3.save(T[0], force=True)
with open(os.path.join(S, LW.STATE_NAME), "rb") as f9:
    snap9 = f9.read()
e9 = dict(ENV)
e9.pop("TJ_BINANCE_KEY")
w3.env_fn = lambda: dict(e9)
a4 = run(w3, 10)
check("N7 그 곳 키를 지움 → '다시 보고 있어요' ✅ 없이 조용히 잊음", not a4 and not w3.st.get("blind"), (heads(a4), w3.st.get("blind")))
with open(os.path.join(S, LW.STATE_NAME), "wb") as f9:
    f9.write(snap9)
MODE["pos"] = "ok"
w4 = mk()
a5 = run(w4, 40)
ok5 = [x for x in blind(a5) if x["text"].startswith("✅ 청산 감시가 바이낸스 선물을 다시 보고 있어요")]
check("N8 재시작 직후 바로 회복 → ✅ '다시 보고 있어요' 1통 · 못 봄 기억 정리", len(ok5) == 1 and len(blind(a5)) == 1 and not w4.st.get("blind"),
      (heads(a5), w4.st.get("blind")))

reset()
w = mk()
run(w, 10)
MODE["pos"] = "401"
run(w, 10)
j9 = w.jobs["acct:binance"]
check("K2 들고 있는 것 없는 곳의 권한 오류 = 종전 6시간 쉼", j9["until"] - T[0] > 5 * 3600, j9["until"] - T[0])
a = run(w, 320)
st5 = (common.read_json(os.path.join(S, LW.STATE_NAME), {}).get("status") or {}).get("venues", {}).get("binance") or {}
a += run(w, 300)
st9 = (common.read_json(os.path.join(S, LW.STATE_NAME), {}).get("status") or {}).get("venues", {}).get("binance") or {}
check("K2 … 텔레그램 0 · 상태 bl 0(들고 있는 것 없는 곳의 권한 오류 = 그 상품 권한 없는 키 — 늘 주황 소음 금지)", not a and st5.get("bl") == 0 and st9.get("bl") == 0,
      (heads(a), st5, st9))
reset()
w = mk()
run(w, 10)
MODE["pos"] = "timeout"
a = run(w, 320)
st5 = (common.read_json(os.path.join(S, LW.STATE_NAME), {}).get("status") or {}).get("venues", {}).get("binance") or {}
a += run(w, 300)
st9 = (common.read_json(os.path.join(S, LW.STATE_NAME), {}).get("status") or {}).get("venues", {}).get("binance") or {}
check("K2 들고 있는 것 없는 곳 타임아웃 지속 → 텔레그램 0 · 5분엔 bl 0 · 10분 넘으면 bl 1(주황 — 새 포지션 발견이 늦음)",
      not a and st5.get("bl") == 0 and st9.get("bl") == 1, (heads(a), st5, st9))
reset()
POS[:] = [{"sym": "ETHUSDT", "amt": -1.0, "liq": 4000.0}]
MARK["ETHUSDT"] = 3000.0
w = mk()
run(w, 20)
w.save(T[0], force=True)
MODE["pos"] = "401"
w2 = mk()
a = run(w2, 10)
j9 = w2.jobs["acct:binance"]
check("K3 재시작 뒤 첫 조회부터 401 — 재시작 전 상태로 '들고 있음' → 5분 뒤 다시(6시간 아님)", 0 < j9["until"] - T[0] <= PRH, j9["until"] - T[0])
a = run(w2, 300)
b = blind(a)
check("K3 … 5분 넘게 못 읽음 → '못 보고 있어요' 1통(마지막 정상 = 재시작 전 · 마지막으로 본 위험도 = 재시작 전 값)",
      len(b) == 1 and "(재시작 전)" in b[0]["text"] and "ETHUSDT 숏 청산가까지" in b[0]["text"], [x["text"] for x in b] or heads(a))

reset()
ENV_L = dict(ENV, TJ_OKX_KEY="o" * 16, TJ_OKX_SECRET="p" * 16, TJ_OKX_PASSPHRASE="q" * 8)
ENV_L.pop("TJ_BINANCE_KEY")
LOANS[:] = [{"ordId": "1", "collateralData": [{"ccy": "ETH", "amt": "10"}], "loanData": [{"ccy": "USDT", "amt": "10000"}],
             "marginCallLTV": "0.8", "liqLTV": "0.9", "riskWarningData": {}, "_ref": (0.5, 2000.0, "ETH")}]
SPOT["ETH"] = 2000.0
w = mk(ENV_L)
a0 = run(w, 70)
MODE["loan"] = "401"
a1 = run(w, 700)
b1 = blind(a1)
check("L1 대출 조회 실패 5분 → 🔴 'OKX 담보대출을 못 보고 있어요'(대출 문장 · LOAN_RISK)", not a0 and len(b1) == 1 and b1[0]["kind"] == "LOAN_RISK"
      and b1[0]["text"].startswith("🔴 청산 감시가 OKX 담보대출을 못 보고 있어요\n거래소(앱·웹)에서 대출·담보를 직접 확인")
      and "LTV 50.0%" in b1[0]["text"], [x["text"] for x in b1] or heads(a1))
check("L1 들고 있는 대출의 권한 오류 = 5분 뒤 다시", 0 < w.jobs["risk:okx_loan"]["until"] - T[0] <= PRH, w.jobs["risk:okx_loan"]["until"] - T[0])
SPOT["ETH"] = 1380.0
a2 = run(w, 10)
r2 = [x for x in a2 if (x.get("lw") or {}).get("g") == "risk"]
check("L2 거래소 값이 11분 낡아도 신선한 담보 시세 추정으로 1단계 🔴(문장 '거래소 값 N분 전 · 조회 실패 중')",
      len(r2) == 1 and "마진콜 문턱의 90%" in r2[0]["text"] and "분 전 · 조회 실패 중" in r2[0]["text"], [x["text"] for x in a2])
b2 = blind(a2)
check("L2 … 위험 구간 진입 → 못 봄 긴급 문장 1번 더(담보 문장)", len(b2) == 1 and "(긴급)" in b2[0]["text"] and "담보를 넣거나 갚으세요" in b2[0]["text"],
      [x["text"] for x in b2])
MODE["loan"] = "ok"
SPOT["ETH"] = 2000.0
a3 = run(w, 400)
check("L3 다시 보이면 ✅ 'OKX 담보대출을 다시 보고 있어요' 1통", len([x for x in blind(a3) if x["text"].startswith("✅ 청산 감시가 OKX 담보대출을 다시")]) == 1,
      heads(a3))

hset = HH.settings({})
base_obs = {"now": T[0], "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in hset["units"]}}


def hchecks(st, ts=None):
    lw = {"ts": T[0] - 5 if ts is None else ts, "status": st}
    return {c["id"]: c for c in HH.evaluate(dict(base_obs, now=T[0], liqw=lw), hset) if c["id"].startswith("liq:")}


ven = {"binance": {"ok": False, "kind": "perm", "err": "HTTP 401", "n": 1, "read": int(T[0] - 400), "bl": 2, "since": int(T[0] - 400),
                   "where": "바이낸스 선물", "hold": True, "danger": False, "worst": "BTCUSDT 롱 청산가까지 16.7%(알림 기준 10%)"},
       "bybit": {"ok": True, "n": 0, "read": int(T[0] - 2), "bl": 0, "since": int(T[0] - 2), "where": "바이빗 선물"},
       "okx": {"ok": False, "kind": "net", "n": 0, "read": None, "bl": 1, "since": int(T[0] - 400), "where": "OKX 선물"}}
rk = {"okx_loan": {"ok": False, "kind": "perm", "n": 1, "read": int(T[0] - 200), "bl": 3, "since": int(T[0] - 200), "where": "OKX 담보대출",
                   "hold": True, "danger": True, "worst": "OKX 담보대출 LTV 75.0% · 마진콜 80.0%"}}
cs = hchecks({"on": True, "venues": ven, "risk": rk})
cb, cy, co, cl = cs.get("liq:see:binance"), cs.get("liq:see:bybit"), cs.get("liq:see:okx"), cs.get("liq:see:okx_loan")
check("H1 들고 있는 곳을 못 봄 = 빨강 '청산 감시가 바이낸스 선물 못 봄' · 상세에 마지막 정상·위험도·원인 · 텔레그램은 감시가 직접(notify 없음)",
      cb and cb["level"] == "crit" and cb["title"] == "청산 감시가 바이낸스 선물 못 봄" and "마지막으로 본 위험도: BTCUSDT 롱" in cb["detail"]
      and "API 키 권한 오류" in cb["detail"] and "마지막 정상" in cb["detail"] and cb["notify"] is False and cb["since"] == int(T[0] - 400), cb)
check("H2 정상 곳 = ok · 들고 있는 것 없는 곳 = 주황(발견 늦음) · 위험 구간 대출 = 빨강 '마지막에 위험 구간'",
      cy and cy["level"] == "ok" and co and co["level"] == "warn" and "발견이 늦어요" in co["detail"]
      and cl and cl["level"] == "crit" and cl["title"].endswith("마지막에 위험 구간"), (cy, co, cl))
cs2 = hchecks({"on": True, "venues": ven, "risk": rk}, ts=T[0] - 900)
check("H3 감시 판이 멈춤(liq:watch 빨강) = 곳별 점검은 판단 보류(같은 일 두 줄 금지)", "liq:watch" in cs2 and not [k for k in cs2 if k.startswith("liq:see:")], list(cs2))
cs3 = hchecks({"on": True, "venues": {"binance": {"ok": False, "n": 1, "read": 1}}, "risk": {}})
check("H4 옛 코드가 쓴 상태 파일(못 봄 칸 없음) = 곳별 점검 없음", not [k for k in cs3 if k.startswith("liq:see:")], list(cs3))
st_h = {}
inc = []
for i in range(4):
    inc += HH.step(st_h, list(hchecks({"on": True, "venues": ven, "risk": rk}).values()), T[0] + 60 * i, hset)
opened = [i for t, i in inc if t == "open" and i["check"] == "liq:see:binance"]
check("H5 빨강 2번 이어지면 사건 열림(상태 패널 빨강) · 텔레그램 대상 아님(notify False)", opened and opened[0]["level"] == "crit" and opened[0]["notify"] is False,
      [(t, i["check"], i["level"]) for t, i in inc])

reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(16.7)
w = mk()
seq = []
for d, sec in ((16.7, 60), (9, 120), (4, 120), (12, 600), (12, 3600), (0.5, 600), (-0.2, 600)):
    MARK["BTCUSDT"] = long_at(d)
    seq.append((d, heads(near(run(w, sec, step=2.0 if sec <= 600 else 10.0)))))
got = dict((i, x) for i, (_d, x) in enumerate(seq))
check("X1 9% → 1통 · 4% → 1통 · 12%(해소 15% 미만)에 1시간 머묾 → 0 · 0.5%(반등 뒤 재진입) → 1통 '다시' · 청산가 통과 → 1통",
      len(got[1]) == 1 and len(got[2]) == 1 and not got[3] and not got[4] and len(got[5]) == 1 and "다시 청산가까지 0.5%" in got[5][0]
      and len(got[6]) == 1 and "닿았거나 지났어요" in got[6][0], seq)
a = run(w, 3600, step=10.0)
check("X2 청산가를 지난 채 1시간 → '아직 … 닿았거나 지난 상태예요(N째)' 1통(2단계 뒤 1시간마다)", len(near(a)) == 1 and "아직 청산가에 닿았거나 지난 상태예요" in near(a)[0]["text"],
      heads(a))
reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(9)
w = mk()
a0 = run(w, 30)
MARK["BTCUSDT"] = long_at(4)
a1 = run(w, 30)
a2 = run(w, 3540, step=10.0)
a3 = run(w, 120, step=10.0)
a4 = run(w, 3600, step=10.0)
check("X3 2단계(4%) 뒤 같은 자리 1시간 = 그 전 0 · 1시간에 '아직 청산가까지 4.0% 남았어요(1시간째)' 1통 · 다음 1시간에 1통",
      len(near(a0)) == 1 and len(near(a1)) == 1 and not near(a2) and len(near(a3)) == 1 and "아직 청산가까지 4.0% 남았어요(1시간째)" in near(a3)[0]["text"]
      and len(near(a4)) == 1, (heads(a2), heads(a3), heads(a4)))
wcfg({"alerts": {"liq_repeat_min": 0}})
a5 = run(w, 7300, step=10.0)
check("X4 설정 alerts.liq_repeat_min = 0 → 다시 알림 끔", not near(a5), heads(a5))
wcfg({"alerts": {"liq_repeat_min": 30}})
a6 = run(w, 10)
a7 = run(w, 1790, step=10.0)
a8 = run(w, 20, step=10.0)
check("X4 설정 30분 → 바로 1통(마지막 알림이 30분 넘음) · 그 뒤 30분마다", len(near(a6)) == 1 and not near(a7) and len(near(a8)) == 1, (heads(a6), heads(a7), heads(a8)))
wcfg({})
rs9 = getattr(LW, "repeat_sec", lambda c: None)
check("X4 설정값 읽기 — 없음 60분 · 0 끔 · 1 → 5분(하한) · 9999 → 1440분 · 문자 → 60분",
      (rs9({}), rs9({"alerts": {"liq_repeat_min": 0}}), rs9({"alerts": {"liq_repeat_min": 1}}),
       rs9({"alerts": {"liq_repeat_min": 9999}}), rs9({"alerts": {"liq_repeat_min": "x"}})) == (3600.0, 0.0, 300.0, 86400.0, 3600.0))
reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(20)
w = mk()
run(w, 20)
a = []
for i in range(20):
    MARK["BTCUSDT"] = long_at(9.9 if i % 2 == 0 else 10.6)
    a += run(w, 20)
check("X5 기준 경계 깜빡임(9.9% ↔ 10.6%) 20번 = 처음 1통뿐(반등은 기준 1.1배 밖부터)", len(near(a)) == 1, heads(a))
mem = {}
r0 = {"key": "binance:Q:LONG:", "name": "Q 롱", "ex": "binance", "dist": 0.0, "mark": 90.0, "liq": 100.0, "side": "LONG", "alert_ok": True, "resolve_ok": True}
o1 = LW.judge_futures(mem, [r0], [], 10.0, 1000.0)
o2 = LW.judge_futures(mem, [r0], [], 10.0, 1010.0)
check("X6 처음 본 값이 청산가를 지남 → 1통 · 기억 3단계 · 다음 판 0", len(o1) == 1 and mem["binance:Q:LONG:"]["st"] == 3 and not o2, (o1, o2, mem))
memr = {}
rowr = {"key": "okx:loan:loan:z", "kind": "loan", "label": "OKX 담보대출", "metric": "ltv", "m": {"unit": "frac", "risk": "up", "thr_src": "api:x"},
        "call": 0.8, "liq": 0.9, "age": 10}
o = LW.judge_risk(memr, [dict(rowr, r=0.81, alert_ok=True, resolve_ok=True)], [], 1000)
o += LW.judge_risk(memr, [dict(rowr, r=0.81, alert_ok=True, resolve_ok=True)], [], 1000 + 3599)
o_rep = LW.judge_risk(memr, [dict(rowr, r=0.81, alert_ok=True, resolve_ok=True)], [], 1000 + 3600)
o_old = LW.judge_risk(memr, [dict(rowr, r=0.81, age=900, pfresh=False, alert_ok=True, resolve_ok=False)], [], 1000 + 7300)
check("X7 대출 마진콜 이어짐 → 1시간 전 0 · 1시간에 '아직 마진콜 구간이에요(1시간째)' 1통 · 낡은 값뿐이면 다시 알림 안 함(못 봄 알림이 맡음)",
      len(o) == 1 and len(o_rep) == 1 and "아직 마진콜 구간이에요(1시간째)" in o_rep[0][1] and not o_old, (o, o_rep, o_old))
o_dn = LW.judge_risk(memr, [dict(rowr, r=0.70, alert_ok=True, resolve_ok=True)], [], 9000)
st_dn = memr["okx:loan:loan:z"]["st"]
o_up = LW.judge_risk(memr, [dict(rowr, r=0.81, alert_ok=True, resolve_ok=True)], [], 9010)
check("X8 대출 반등(마진콜 5% 넘게 아래 · 해소 전 — 알림 0 · 기억 1단계로) 뒤 다시 마진콜 → 다시 1통", not o_dn and st_dn == 1 and len(o_up) == 1
      and "마진콜에 닿았어요" in o_up[0][1], (o_dn, st_dn, o_up, memr))
memr2 = {"okx:loan:loan:y": {"st": 2, "at": 0, "label": "t"}}
o_f = []
for i, rr in enumerate((0.79, 0.81, 0.79, 0.81, 0.795, 0.80)):
    o_f += LW.judge_risk(memr2, [dict(rowr, key="okx:loan:loan:y", r=rr, alert_ok=True, resolve_ok=True)], [], 100 + i)
check("X8 마진콜 경계 깜빡임(79%↔81%) = 다시 알림 0", not o_f and memr2["okx:loan:loan:y"]["st"] == 2, (o_f, memr2))
check("Z 외부 호출은 전부 목(실제 네트워크 0)", all(c[1] in ("fapi.binance.com", "api.binance.com", "www.okx.com") for c in CALLS))
H.finish()
