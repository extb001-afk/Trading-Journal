#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

W1, W2, W3 = ("0x" + c * 40 for c in "123")
D = 86400
NOW = 400 * D
json.dump({"wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "w1"}], "chains": {"eth": {}}},
          open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
import rabby  # noqa: E402

chk = T.chk
EV = 24 * 3600.0


def w(total, ago=2 * D, prot=None):
    return {"fetchedAt": NOW - ago, "total": total, "protocols": prot or [], "tokens": [], "chains": []}


we = rabby.wallet_every
chk(we(w(10_000), 10_000, EV) == rabby.RB_EVERY_SAME, "G1a 봇과 같음 = 주 1회(종전)", we(w(10_000), 10_000, EV))
chk(we(w(10_000), 8_000, EV) == EV, "G1b Rabby 가 20% 많음 = every_sec(하루)", we(w(10_000), 8_000, EV))
chk(we(w(8_000), 10_000, EV) == EV, "G1c Rabby 가 20% 적음(봇이 많음 · 출금 뒤 낡은 값 반대 꼴) = every_sec", we(w(8_000), 10_000, EV))
chk(we(w(5_000), 4_750, EV) == rabby.RB_EVERY_SAME and we(w(5_000), 4_749, EV) == EV,
    "G1d 경계 — 차 = 큰 쪽의 5%($250) = 주 1회 · 넘으면 하루", (we(w(5_000), 4_750, EV), we(w(5_000), 4_749, EV)))
chk(we(w(1_500), 1_350, EV) == rabby.RB_EVERY_SAME and we(w(1_500), 1_299, EV) == EV,
    "G1e 작은 지갑 = $200 하한(차 $150 = 주 1회 · $201 = 하루)", (we(w(1_500), 1_350, EV), we(w(1_500), 1_299, EV)))
chk(we(w(10_000), None, EV) == rabby.RB_EVERY_SAME, "G1f 봇 값 모름(None) = 종전 주 1회", we(w(10_000), None, EV))
chk(we(w(0.5), 0.2, EV) == rabby.RB_EVERY_EMPTY and we(w(0.5), None, EV) == rabby.RB_EVERY_EMPTY, "G1g 빈 지갑 = 월 1회(종전)", None)
chk(we(w(10_000, prot=[{"x": 1}]), 10_000, EV) == EV, "G1h 프로토콜 있던 지갑 = every_sec(종전)", None)
chk(we({}, 5_000, EV) == 0.0 and we({"total": 1}, 5_000, EV) == 0.0, "G1i 받은 적 없음 = 0(바로 · 종전)", None)
chk(we(w(10_000), "x", EV) == EV, "G1j 봇 값 숫자 아님 = every_sec(종전)", we(w(10_000), "x", EV))
chk(we(w(10_000), 0, EV) == EV, "G1k 봇 평가 0 · Rabby $1만(봇이 모르는 자산) = 하루", we(w(10_000), 0, EV))

st = {"wallets": {W1: w(10_000), W2: w(10_000), W3: w(10_000)}}
chk(rabby.due_wallet(st, [W1], NOW, EV, {W1: 7_000}) == W1, "G2a 2일 전 받은 지갑 · 봇과 30% 차이 = 차례", None)
chk(rabby.due_wallet(st, [W2], NOW, EV, {W2: 10_050}) is None, "G2b 같음 = 차례 아님(주 1회 전)", None)
chk(rabby.due_wallet(st, [W3], NOW, EV, {}) is None, "G2c 봇 값 모름 = 차례 아님(종전)", None)
st["wallets"][W1]["triedAt"] = NOW - 3600
chk(rabby.due_wallet(st, [W1], NOW, EV, {W1: 7_000}) is None, "G2d 3시간 안 시도 = 양보(종전)", None)
st["wallets"][W1].pop("triedAt")
chk(rabby.due_wallet(st, [W1, W2], NOW, EV, {W1: 7_000, W2: 10_050}) == W1, "G2e 같이 있으면 차이 큰 지갑만 차례", None)

calls = []


def fake_get(u):
    calls.append(u)
    if "complex_protocol_list" in u:
        return []
    return {"total_usd_value": 10_000.0, "chain_list": [{"id": "eth", "community_id": 1, "name": "Ethereum", "usd_value": 10_000.0}]}


rp = os.path.join(paths.STATE_DIR, "rabby_g3.json")
cfg = {"wallets": [{"type": "evm", "chain": "eth", "address": a} for a in (W1, W2, W3)], "chains": {"eth": {}},
       "rabby": {"enabled": True, "min_wallet_usd": 0, "daily_calls_max": 4}}
json.dump({"v": 1, "wallets": {W1: w(10_000), W2: w(10_000), W3: w(10_000)},
           "calls": {__import__("timeutil").kst_day(NOW): 4}}, open(rp, "w"))
BU = {W1: 5_000.0, W2: 5_000.0, W3: 5_000.0}
r0 = T.safe(rabby.refresh_once, cfg, rp, now=NOW, get=fake_get, sleep=lambda s: None, bot_usd=BU)
chk(r0 == "cap" and calls == [], "G3a 하루 상한이 찼으면 차이 큰 지갑이 있어도 'cap' · 외부 조회 0번", (r0, calls))
st3 = json.load(open(rp))
st3["calls"] = {}
json.dump(st3, open(rp, "w"))
per_day = {}
for k in range(6 * 24 * 6):
    t = NOW + k * 600
    n0 = len(calls)
    r = T.safe(rabby.refresh_once, cfg, rp, now=t, get=fake_get, sleep=lambda s: None, bot_usd=BU)
    day = __import__("timeutil").kst_day(t)
    per_day[day] = per_day.get(day, 0) + (len(calls) - n0)
    if isinstance(r, dict):
        break
st3 = json.load(open(rp))
chk(max(per_day.values()) <= 4 and sum(per_day.values()) > 0, "G3b 며칠 돌려도 날마다 호출 ≤ 상한(4)", per_day)
chk(all(v <= 4 for v in (st3.get("calls") or {}).values()), "G3c 파일의 날짜별 호출 수 ≤ 상한", st3.get("calls"))
nb = [sum(1 for u in calls if "total_balance" in u and u.endswith(a)) for a in (W1, W2, W3)]
chk(all(x >= 4 for x in nb), "G3d 차이 큰 지갑 = 6일 동안 거의 하루마다 다시 받음(상한 4콜·지갑당 2콜이라 하루 2지갑 — 지갑마다 4번 이상 · 종전 = 주 1회라 1번)", nb)
calls.clear()
json.dump({"v": 1, "wallets": {W1: w(10_000), W2: w(10_000), W3: w(10_000)}}, open(rp, "w"))
for k in range(5 * 24 * 6):
    T.safe(rabby.refresh_once, cfg, rp, now=NOW + k * 600, get=fake_get, sleep=lambda s: None, bot_usd={W1: 10_000.0, W2: 10_000.0, W3: 10_000.0})
chk(calls == [], "G3e 봇과 같은 지갑 = 5일 동안 다시 안 받음(주 1회 · 종전)", len(calls))

for rb9, b9 in ((10_000, 9_500), (10_000, 9_499), (100, 350), (1_000, 1_200), (1_000, 1_201), (5_000, 2), (3, 5_000)):
    far9 = rabby.need_protocols({"fetchedAt": NOW - D, "protocols": []}, b9, rb9, now=NOW)
    chk((we(w(rb9), b9, EV) == EV) is far9, f"G4 Rabby {rb9} · 봇 {b9}: 주기 '다름' 판정 = 2콜째 판정(need_protocols)과 같은 식", (we(w(rb9), b9, EV), far9))

T.finish()
