#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

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


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:700])


common.atomic_write_json(CFG, {})
common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
T = [1_800_000_000.0]
MODE = {"bn": "ok", "hl": "ok"}
MARK = {}
POS = []
CALLS = []


def router(method, url, headers=None, body=None, timeout=6.0):
    u = urllib.parse.urlsplit(url)
    host, path, qs = u.hostname, u.path, dict(urllib.parse.parse_qsl(u.query))
    CALLS.append((T[0], host, path))
    if host in ("fapi.binance.com", "api.binance.com") and path != "/fapi/v1/premiumIndex":
        if MODE["bn"] == "401":
            raise LW.HttpErr(401, '{"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}')
        if MODE["bn"] == "timeout":
            raise TimeoutError("timed out")
    if host == "api.hyperliquid.xyz" and path == "/info":
        if MODE["hl"] == "timeout":
            raise TimeoutError("timed out")
        return 200, {}, {"assetPositions": [], "marginSummary": {}}
    if host == "fapi.binance.com":
        if path == "/fapi/v3/positionRisk":
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
    raise LW.HttpErr(404, "not found")


LW.HTTP = router
ENV = {"TJ_TG_TOKEN": "000:fake", "TJ_TG_CHAT": "1", "TJ_BINANCE_KEY": "k" * 16, "TJ_BINANCE_SECRET": "s" * 16}


def reset():
    for fn in (LW.STATE_NAME, AP.FAST_QUEUE):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    MODE.update(bn="ok", hl="ok")
    POS[:] = []
    MARK.clear()
    CALLS[:] = []


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
    return [x["text"].split("\n")[0][:90] for x in xs]


def blind(xs):
    return [x for x in xs if (x.get("lw") or {}).get("g") == "blind"]


def near(xs):
    return [x for x in xs if (x.get("lw") or {}).get("g") == "fut"]


def vstat(name="binance", sec="venues"):
    return ((common.read_json(os.path.join(S, LW.STATE_NAME), {}).get("status") or {}).get(sec) or {}).get(name) or {}


def long_at(dist_pct, liq=50000.0):
    return liq / (1 - dist_pct / 100)


reset()
w = mk()
a0 = run(w, 20)
MODE["bn"] = "401"
t401 = T[0]
a1 = run(w, 330, step=5.0)
st5 = vstat()
a1 += run(w, 330, step=5.0)
st11 = vstat()
a2 = run(w, 3000, step=5.0)
b2 = blind(a0 + a1 + a2)
check("S1 포지션 없음 → 20초 정상 → 401 1시간: 🔴 '청산 감시가 바이낸스 선물 · 바이낸스 마진 · 바이낸스 담보대출을 … 못 보고 있어요' 1통(거래소별 한 통)",
      len(b2) == 1 and b2[0]["text"].startswith("🔴 청산 감시가 바이낸스 선물") and "못 보고 있어요" in b2[0]["text"]
      and "새로 열면 청산 경고를 못 받아요" in b2[0]["text"] and "API 키·IP 허용 목록" in b2[0]["text"] and "API 키 권한 오류" in b2[0]["text"]
      and b2[0]["kind"] == "LIQ_NEAR", [x["text"] for x in b2] or heads(a1 + a2))
t_b = (b2[0]["ts"] - t401) if b2 else None
check("S1 … 알림 = 401 시작(마지막 정상) 뒤 1시간(±1분)", t_b is not None and 3540 <= t_b <= 3660, t_b)
check("S2 5분엔 상태 bl 0 · 10분 넘으면 bl 1(주황 — 권한 오류라도 읽은 적 있는 곳)", st5.get("bl") == 0 and st11.get("bl") == 1 and st11.get("kind") == "perm",
      (st5, st11))
pr = [c for c in CALLS if c[2] == "/fapi/v3/positionRisk" and c[0] > t401]
check("S3 권한 오류 재시도 = 5·10·20·30분(1시간 10분에 4~6번 — 종전 6시간 쉼)", 4 <= len(pr) <= 6 and 0 < w.jobs["acct:binance"]["until"] - T[0] <= 1800,
      ([int(c[0] - t401) for c in pr], w.jobs["acct:binance"]["until"] - T[0]))
a3 = run(w, 3 * 3600, step=20.0)
check("S4 그 뒤 3시간 더 못 봄 → 더 안 보냄(1통뿐)", not blind(a3), heads(a3))
MODE["bn"] = "ok"
a4 = run(w, 1900, step=5.0)
b4 = blind(a4)
check("S5 다시 보이면 ✅ '바이낸스 선물을 다시 보고 있어요' 1통(묶인 곳들은 조용히) · 기억 정리",
      len(b4) == 1 and b4[0]["text"].startswith("✅ 청산 감시가 바이낸스 선물을 다시 보고 있어요") and b4[0].get("resolved") and not w.st.get("blind"),
      (heads(a4), w.st.get("blind")))
check("S5 … 그 사이 위험 알림·다른 줄 0", not [x for x in a0 + a1 + a2 + a3 + a4 if (x.get("lw") or {}).get("g") != "blind"], heads(a0 + a1 + a2 + a3 + a4))

reset()
MODE["bn"] = "401"
w = mk()
a = run(w, 2 * 3600, step=10.0)
check("S6 처음부터 401(한 번도 못 읽음 — 그 상품 권한 없는 키) 2시간 → 텔레그램 0 · 상태 bl 0 · 6시간 쉼(종전)",
      not a and vstat().get("bl") == 0 and w.jobs["acct:binance"]["until"] - T[0] > 3 * 3600, (heads(a), vstat(), w.jobs["acct:binance"]["until"] - T[0]))

reset()
w = mk()
run(w, 20)
w.save(T[0], force=True)
MODE["bn"] = "401"
w2 = mk()
a = run(w2, 3700, step=10.0)
check("S7 읽은 뒤 재시작 · 재시작 직후부터 401 → 1시간 뒤 1통(읽은 적 있음은 상태 파일에 남음)", len(blind(a)) == 1 and "못 보고 있어요" in blind(a)[0]["text"],
      heads(a))
w2.save(T[0], force=True)
w3 = mk()
a = run(w3, 3700, step=10.0)
check("S7 … 또 재시작해도 같은 못 봄 알림 다시 0(기억 · 긴급 줄 기록)", not blind(a), heads(a))

reset()
w = mk()
run(w, 20)
e2 = dict(ENV, TJ_BINANCE_KEY="n" * 16)
w.env_fn = lambda: dict(e2)
MODE["bn"] = "401"
a = run(w, 2 * 3600, step=10.0)
check("S8 키를 바꾼 뒤 새 키가 처음부터 401 → 무음(새 키는 '읽은 적 없음'부터)", not a and not (w.st.get("seen") or {}).get("f:binance"), (heads(a), w.st.get("seen")))

reset()
w = mk()
run(w, 20)
MODE["bn"] = "timeout"
a = run(w, 3700, step=5.0)
b = blind(a)
check("S9 포지션 없는 곳 타임아웃 1시간 → 1통(문장 '연결이 돌아오면 저절로 이어져요')", len(b) == 1 and "연결이 돌아오면 저절로 이어져요" in b[0]["text"]
      and "연결 실패·시간 초과" in b[0]["text"], [x["text"] for x in b] or heads(a))

reset()
A1, A2 = "0x" + "ab" * 20, "0x" + "cd" * 20
common.atomic_write_json(CFG, {"perp_wallets": [{"dex": "hyperliquid", "address": A1, "label": "a"}, {"dex": "hyperliquid", "address": A2, "label": "b"}]})
time.sleep(0.01)
w = mk({k: v for k, v in ENV.items() if not k.startswith("TJ_BINANCE")})
run(w, 20)
MODE["hl"] = "timeout"
a = run(w, 3700, step=5.0)
b = blind(a)
check("S10 하이퍼리퀴드 주소 2개 · 공개 API 1시간 장애 → 1통(두 주소를 한 문장에)", len(b) == 1 and b[0]["text"].count("하이퍼리퀴드 지갑") == 2, heads(a))
MODE["hl"] = "ok"
a = run(w, 30)
check("S10 … 회복 = ✅ 1통(묶인 주소는 조용히)", len(blind(a)) == 1 and blind(a)[0]["text"].startswith("✅"), heads(a))
common.atomic_write_json(CFG, {})
time.sleep(0.01)

reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(6)
w = mk()
a = run(w, 6 * 3600, step=10.0)
n = near(a)
check("R1 1단계(6%)에 6시간 → 약 6통(처음 + 1시간마다 '아직 청산가까지 6.0% 남았어요')", 5 <= len(n) <= 7 and all("6.0%" in x["text"] for x in n)
      and any("아직 청산가까지 6.0% 남았어요" in x["text"] for x in n), heads(n))
reset()
POS[:] = [{"sym": "BTCUSDT", "amt": 0.1, "liq": 50000.0}]
MARK["BTCUSDT"] = long_at(20)
w = mk()
run(w, 20)
a = []
for i in range(24):
    MARK["BTCUSDT"] = long_at(9 if i % 2 == 0 else 12)
    a += run(w, 150, step=5.0)
n = near(a)
check("R2 기준선 오르내림(9% ↔ 12% · 2분 30초마다) 1시간 → 4통 이하(재진입 최소 15분 · 종전 12통)", 1 <= len(n) <= 4, heads(n))
gaps = [n[i + 1]["ts"] - n[i]["ts"] for i in range(len(n) - 1)]
check("R2 … 알림 사이 15분 이상", all(g9 >= 900 for g9 in gaps), gaps)
memr = {}
rowr = {"key": "okx:loan:loan:z", "kind": "loan", "label": "OKX 담보대출", "metric": "ltv", "m": {"unit": "frac", "risk": "up", "thr_src": "api:x"},
        "call": 0.8, "liq": 0.9, "age": 10}
o = []
t9 = 1000.0
for i in range(13):
    o += LW.judge_risk(memr, [dict(rowr, r=0.81 if i % 2 == 0 else 0.70, alert_ok=True, resolve_ok=True)], [], t9)
    t9 += 300
hd = [x[1].split("\n")[0] for x in o]
check("R3 대출 마진콜 ↔ 반등(5분마다) 1시간 → 4통 이하(재진입 최소 15분)", 1 <= len(o) <= 4, hd)
memr = {}
o = LW.judge_risk(memr, [dict(rowr, r=0.73, alert_ok=True, resolve_ok=True)], [], 1000)
o += LW.judge_risk(memr, [dict(rowr, r=0.81, alert_ok=True, resolve_ok=True)], [], 1060)
o += LW.judge_risk(memr, [dict(rowr, r=0.86, alert_ok=True, resolve_ok=True)], [], 1120)
check("R4 대출 단계가 새로 오름(1→2→3) = 15분 안이라도 매번 알림", len(o) == 3, [x[1].split("\n")[0] for x in o])
check("Z 외부 호출은 전부 목(실제 네트워크 0)", all(c[1] in ("fapi.binance.com", "api.binance.com", "api.hyperliquid.xyz") for c in CALLS))
H.finish()
