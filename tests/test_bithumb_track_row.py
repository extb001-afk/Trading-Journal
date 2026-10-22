#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402

json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import exf_bithumb as B  # noqa: E402

chk = T.chk
NOW = int(time.time())
DAY = 86400
KST = datetime.timezone(datetime.timedelta(hours=9))
T.patch_moved("PACE", 0, ("exf_",))
T.patch_moved("_gov_prepare", lambda *_a, **_k: None, ("exf_",))
T.patch_moved("_srv_ms", lambda *_a, **_k: NOW * 1000, ("exf_",))
ENV = {"TJ_BITHUMB_KEY": "k", "TJ_BITHUMB_SECRET": "s"}


def iso(t):
    return datetime.datetime.fromtimestamp(t, KST).isoformat()


def order(u, created, vol="1", funds="100"):
    return {"uuid": u, "market": "KRW-BTC", "side": "bid", "ord_type": "limit", "price": "100", "state": "done",
            "created_at": iso(created), "executed_volume": vol, "executed_funds": funds, "paid_fee": "0.04"}


ORD, OPEN = [], []
MODE = {"single": "ok"}
CALLS = {"single": 0}


def http(url, headers=None, **_k):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    if u.path == "/v1/orders":
        if q.get("state") == "wait":
            return list(OPEN)
        if q.get("state") != "done":
            return []
        p = int(q["page"])
        rows = sorted(ORD, key=lambda r: r["created_at"], reverse=True)
        return rows[(p - 1) * 100: p * 100]
    if u.path == "/v1/order":
        CALLS["single"] += 1
        if MODE["single"] == "404":
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        o = dict(next(x for x in ORD + OPEN if x["uuid"] == q["uuid"]))
        o.update(state="done", executed_volume="1", executed_funds="100")
        o["trades"] = [{"created_at": iso(NOW - 600), "funds": "100", "volume": "1"}]
        o["trades_count"] = 1
        return o
    raise AssertionError(u.path)


T.patch_moved("http_json", http, ("exf_",))


def cycle(fst, t0):
    st = json.loads(json.dumps(fst))
    f = B.fills_bithumb(ENV, st, t0, NOW)
    seen = st.setdefault("seen", {})
    new = [x for x in f if x["id"] not in seen]
    for x in new:
        seen[x["id"]] = x["ts"]
    st["backfilled_until"] = NOW
    return st, new


print("[1] 첫 백필")
ORD[:] = [order(f"u{i:04d}", NOW - (i + 1) * 12 * 3600) for i in range(200)]
MODE["single"] = "404"
CALLS["single"] = 0
st, new = cycle({}, NOW - 150 * DAY)
chk(len(new) == 200, "[1] 첫 주기 200건 전부 방출(목록 행)", len(new))
chk(CALLS["single"] == 0 and not st.get("open_track"), "[1] 단건 조회 0 · 대기열 0", {"single": CALLS["single"], "track": len(st.get("open_track") or {})})

print("[2] 대기열 목록 행 · 404 대체")
ORD[:] = []
st = {"seen": {"bithumb:prev": NOW * 1000}, "backfilled_until": NOW}
OLD9 = order("late1", NOW - 2 * DAY, vol="2", funds="300")
ORD.append(OLD9)
st, new = cycle(st, NOW - 3 * DAY)
ent = (st.get("open_track") or {}).get("late1") or {}
chk(not new and ent.get("closed") and ent.get("nf") == 1, "[2] 30분 넘은 새 종결 주문 = 대기열(첫 404 1회)", ent)
row9 = ent.get("row") or {}
chk(row9.get("executed_volume") == "2" and row9.get("executed_funds") == "300" and set(row9) <= set(B.BITHUMB_TRACK_ROW_KEYS),
    "[2] 대기열에 목록 행 최소 칸 저장(체결 수량·정산 총액 · 정해진 칸만)", row9)
ORD.remove(OLD9)
st, new = cycle(st, NOW - 3 * DAY)
chk(not new and st["open_track"]["late1"].get("nf") == 2, "[2] 404 2회 = 아직 추적", st["open_track"].get("late1"))
st, new = cycle(st, NOW - 3 * DAY)
f9 = [x for x in new if x["id"] == "bithumb:late1"]
chk(len(f9) == 1 and float(f9[0]["qty"]) == 2 and abs(float(f9[0]["price"]) - 150) < 1e-9,
    "[2] 404 3회 = 저장한 목록 행으로 방출(수량 2 · 평균가 150)", f9)
chk(f9 and f9[0]["ts"] == (NOW - 2 * DAY) * 1000, "[2] 방출 시각 = 생성 시각(단건 못 받음 — 종전 대체와 같음)", f9[0]["ts"] if f9 else None)
chk("late1" not in (st.get("open_track") or {}), "[2] 추적 종료")

print("[3] 단건 성공 · 새 주문 · 행 없는 404")
MODE["single"] = "ok"
ORD.append(order("late2", NOW - 2 * DAY))
st, new = cycle(st, NOW - 3 * DAY)
f9 = [x for x in new if x["id"] == "bithumb:late2"]
chk(len(f9) == 1 and f9[0]["ts"] == (NOW - 600) * 1000, "[3] 단건 성공 = 체결 시각(trades 마지막)", f9)
ORD.append(order("fresh", NOW - 60))
st, new = cycle(st, NOW - 3 * DAY)
chk([x["id"] for x in new] == ["bithumb:fresh"] and "fresh" not in (st.get("open_track") or {}), "[3] 30분 안 새 주문 = 바로 방출", [x["id"] for x in new])
MODE["single"] = "404"
OPEN[:] = [{"uuid": "open1", "market": "KRW-BTC", "created_at": iso(NOW - 5 * DAY), "state": "wait"}]
st, new = cycle(st, NOW - 3 * DAY)
chk("open1" in st["open_track"] and not st["open_track"]["open1"].get("closed"), "[3] 미체결 주문 추적 시작", st["open_track"].get("open1"))
OPEN[:] = []
for _ in range(3):
    st, new = cycle(st, NOW - 3 * DAY)
chk("open1" not in st["open_track"] and not [x for x in new if x["id"] == "bithumb:open1"],
    "[3] 목록 행 없는 404 3회 = 추적 종료 · 방출 없음(종전 '수동 확인')", st.get("open_track"))

T.finish()
