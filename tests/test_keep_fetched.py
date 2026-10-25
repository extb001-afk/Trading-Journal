#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

json.dump({"wallets": [], "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
import paths  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
DAY = 86400

import pricing  # noqa: E402

day_old = (int(time.time()) // DAY - 400) * DAY
pc = pricing.PxCache(os.path.join(T.TMP, "px_k1.json"))
store = pc.d["cgday"]
CA_A = "0x" + "a" * 40
store[f"ca:base:{CA_A}:{day_old}"] = [[day_old * 1000, 3.0], [day_old * 1000 + 3_600_000, 3.0]]
for i in range(4100):
    store[f"ca:eth:0x{i:040x}:{day_old}"] = []
n_before = len(store)
v1 = pc.cg_usd_at(day_old * 1000 + 1_800_000, chain="base", ca=CA_A)
chk(len(store) == n_before and f"ca:base:{CA_A}:{day_old}" in store, "K1a 하루 묶음 4,000 개 넘어도 지우지 않음(종전 = 사전순 앞 1,000 삭제)",
    {"before": n_before, "after": len(store)})
chk(v1 == 3.0 and not T.NET_TRIES, "K1b 남은 지난날 묶음을 다시 받지 않고 그대로 씀(바깥 호출 0)", {"v": v1, "net": len(T.NET_TRIES)})
day_now = int(time.time()) // DAY * DAY
now_ms = int(time.time()) * 1000
pricing._CG_MEM[f"ca:base:{CA_A}:{day_now}"] = (time.time(), [[now_ms - 60_000, 4.0], [now_ms + 60_000, 4.0]])
v2 = pc.cg_usd_at(now_ms, chain="base", ca=CA_A)
chk(v2 == 4.0 and f"ca:base:{CA_A}:{day_now}" not in store, "K1c 오늘 묶음 = 메모리에서만 · 디스크 저장본에 안 남음(지금 값 규칙 그대로)",
    {"v": v2})

import fut_rcpt  # noqa: E402

now_ms = 2_000 * DAY * 1000
old = [{"uid": "o1", "ts_ms": now_ms - 900 * DAY * 1000, "px": 1.0}]
many = [{"uid": f"m{i}", "ts_ms": now_ms - 10 * DAY * 1000 + i, "px": 2.0} for i in range(60_010)]
rows = fut_rcpt.merge(old, many, now_ms)
chk(len(rows) == 60_011 and rows[0]["uid"] == "o1", "K2a 900일 전 가격 행·6만 넘는 행 = 남음(종전 = 800일 밖 버림 · 최근 6만만)",
    {"n": len(rows), "first": rows[0]["uid"] if rows else None})
rows2 = fut_rcpt.merge(old + [{"uid": "x1", "ts_ms": now_ms - 1, "px": 5.0}], [{"uid": "x1", "ts_ms": now_ms - 1, "px": 6.0}], now_ms,
                       keep=lambda r: r["uid"] != "o1")
chk([r["uid"] for r in rows2] == ["x1"] and rows2[0]["px"] == 6.0, "K2b keep 거짓 = 버림 · 같은 uid = 새 행 · 시각순(종전 그대로)", rows2)

import nft  # noqa: E402

CLK = [1_700_000_000.0]
nd = os.path.join(T.TMP, "nft_k3")
os.makedirs(nd, exist_ok=True)
tr = nft.Tracker(cfg_fn=lambda: {}, px_fn=lambda s: 2000.0 if s == "ETH" else None, rate_fn=lambda: 1400.0, http=lambda *a, **k: (404, {}),
                 sleep=lambda s: None, now=lambda: CLK[0], env_fn=lambda k: "", gate_fn=lambda: {},
                 hold_path=os.path.join(nd, "hold.json"), fp_path=os.path.join(nd, "fp.json"), prefs_path=os.path.join(nd, "prefs.json"),
                 budget_path=os.path.join(nd, "budget.json"))
KEY = "eth:" + "0x" + "b" * 40
for i in range(450):
    tr._hist_put(KEY, {"native": 1.0 + i / 1000.0, "sym": "ETH"})
    CLK[0] += DAY
hrows = tr.fp["hist"][KEY]
chk(len(hrows) == 450 and hrows[0][1] == 1.0, "K3a 그날 바닥가 450일 = 다 남음(종전 = 최근 400일만)", {"n": len(hrows)})
CLK[0] -= DAY
n3 = len(tr.fp["hist"][KEY])
tr._hist_put(KEY, {"native": 9.0, "sym": "ETH"})
chk(len(tr.fp["hist"][KEY]) == n3 and tr.fp["hist"][KEY][-1][1] == 9.0, "K3b 같은 날 다시 = 마지막 값으로 바꿈(종전 그대로)", None)

import other_assets as oa  # noqa: E402

it = {"hist": []}
oa._hist_add(it, {"date": "2020-01-01", "value": 100.0, "src": "manual"})
for i in range(450):
    oa._hist_add(it, {"date": f"d{i:04d}", "value": 1.0 + i, "src": "auto"})
chk(len(it["hist"]) == 451 and it["hist"][0]["src"] == "manual", "K4a 평가 기록 451 = 다 남음 · 첫 수동 기록 남음(종전 = 400 상한)",
    {"n": len(it["hist"])})
n4 = len(it["hist"])
oa._hist_add(it, {"date": "d0449", "value": 7.0, "src": "auto"})
chk(len(it["hist"]) == n4 and it["hist"][-1]["value"] == 7.0, "K4b 자동 평가 같은 날 = 한 줄(종전 그대로)", None)
qt = oa.Quoter(http_get=lambda *a, **k: (500, b""), sleep=lambda s: None, now=lambda: 1_800_000_000.0,
               store_path=os.path.join(T.TMP, "oa_k4.json"), px_path=os.path.join(T.TMP, "oa_px_k4.json"))
q1 = {"px": 10.0, "cur": "USD", "prev": 9.0, "t": 1, "mday": 0, "name": "X", "exch": "X", "tz": "UTC", "off": 0,
      "closes": [[f"2020-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 1.0] for i in range(300)]}
qt._rec("GC=F", q1, None, "1y")
q2 = dict(q1, closes=[[f"2021-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 2.0] for i in range(300)])
qt._rec("GC=F", q2, None, "1y")
cl = qt.quote_cached("GC=F")["closes"]
chk(len(cl) == 600 and cl[0][0] == "2020-01-01", "K4c 종가 600개 = 다 남음(종전 = 최근 400개)", {"n": len(cl), "first": cl[0] if cl else None})
qt_old = oa.Quoter(http_get=lambda *a, **k: (500, b""), sleep=lambda s: None, now=lambda: 1_800_000_000.0,
                   store_path=os.path.join(T.TMP, "oa_k4b.json"), px_path=os.path.join(T.TMP, "oa_px_k4b.json"))
qt_old._rec("GC=F", dict(q1, closes=cl[-400:]), None, "1y")
item4 = {"id": "oa_k4", "name": "G", "cat": "gold", "auto": "gold", "qty": 10.0, "unit": "g", "cur": "USD", "value": 5.0, "date": "2020-01-01",
         "hist": [{"date": "2019-12-01", "value": 4.0, "qty": 10.0, "cur": "USD", "src": "auto"}]}
ser_new = oa.view({"items": [item4]}, qt, 1400.0, now=1_800_000_000.0)["items"][0]["series"]
ser_old = oa.view({"items": [item4]}, qt_old, 1400.0, now=1_800_000_000.0)["items"][0]["series"]
chk(ser_new == ser_old and 0 < len(ser_new) <= 367, "K4d 차트 점 = 종전 저장 모양과 같음(최근 1년 · 숫자 무변)", {"n": len(ser_new), "old": len(ser_old)})

import rabby  # noqa: E402
from datetime import date, timedelta  # noqa: E402

rp = os.path.join(T.TMP, "rabby_k5.json")
d0 = date(2026, 1, 1)
note = None
for i in range(130):
    note = rabby.daily_note(rp, (d0 + timedelta(days=i)).isoformat(), 1000.0 + i, 1_000_000.0 + i * 120, per_wallet={"0xw": 1000.0 + i})
iso_old = (d0 + timedelta(days=2)).isoformat()
chk(len(note["d"]) == 130 and iso_old in note["d"], "K5a 130일 = 다 남음(종전 = 최근 120일)", {"n": len(note["d"])})
dv = rabby.day_values(note, [iso_old], (d0 + timedelta(days=130)).isoformat(), 5.0)
chk(dv.get(iso_old) == 1002.0, "K5b 120일 넘은 날 = 그날 값으로 쓰임(종전 = 기록 없음 → 빠짐)", dv)
chk(note["n"].get(d0.isoformat()) == 1000.0, "K5c 첫 반영(n) 첫날 남음", note.get("n"))

import addr_ai  # noqa: E402

st6 = addr_ai.Store(os.path.join(T.TMP, "ai_k6"))
os.makedirs(os.path.join(T.TMP, "ai_k6"), exist_ok=True)


def _fill6(d):
    for i in range(addr_ai.STORE_KEEP + 50):
        d["items"][f"k{i}"] = {"at": i, "text": "x"}
        d["err"][f"e{i}"] = {"at": i}


st6._write(_fill6)
d6 = st6.read()
chk(len(d6["items"]) == addr_ai.STORE_KEEP + 50 and "k0" in d6["items"], "K6a 저장 의견 = 개수로 안 지움(종전 = 오래된 것부터 2,000 상한)",
    {"n": len(d6["items"])})
chk(len(d6["err"]) == addr_ai.STORE_KEEP and "e0" not in d6["err"], "K6b 실패 기록(err) = 종전 상한 그대로", {"n": len(d6["err"])})

import sellchart  # noqa: E402

es = sellchart.EvalStore(os.path.join(T.TMP, "ev_k7"), kind="sell")
os.makedirs(os.path.join(T.TMP, "ev_k7"), exist_ok=True)
seed7 = {f"2020-01-01|C{i}|fp": {"at": i, "v": 1} for i in range(12_005)}
with open(es.path, "w", encoding="utf-8") as f:
    json.dump(seed7, f)
ok7 = es.put("2026-01-01", "TKJ", "fpa", {"at": 20_000, "v": 2})
d7 = json.load(open(es.path, encoding="utf-8"))
chk(ok7 and len(d7) == 12_006 and "2020-01-01|C0|fp" in d7, "K7a 전체 1만 2천 개 넘어도 남음(종전 = 오래 쓴 것부터 삭제)", {"n": len(d7)})
for j, fp9 in enumerate(("fpb", "fpc", "fpd")):
    es.put("2026-01-01", "TKJ", fp9, {"at": 20_001 + j, "v": 3})
d7 = json.load(open(es.path, encoding="utf-8"))
same7 = sorted(k for k in d7 if k.startswith("2026-01-01|TKJ|"))
chk(same7 == ["2026-01-01|TKJ|fpb", "2026-01-01|TKJ|fpc", "2026-01-01|TKJ|fpd"], "K7b 같은 [날짜|코인] = 최근 3 지문(대체된 옛 지문 정리 · 종전)", same7)

import flow_trace  # noqa: E402

cache8 = {"_memo": {"blk": {f"bsc|{i}": 1_700_000_000 + i for i in range(6_000)}, "etx": {}, "dec": {}}}
flow_trace.Scanner({"chains": {}}, cache8)
chk(len(cache8["_memo"]["blk"]) == 6_000, "K8 블록 시각 메모 6,000 = 비우지 않음(종전 = 5,000 넘으면 통째 비움)", len(cache8["_memo"]["blk"]))

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import ledger_backup  # noqa: E402
import ledger_restore  # noqa: E402

sd9 = paths.STATE_DIR
for n9 in ("sell_evals.json", "curve_hist_px.json", "futures_px_bybit.json", "daily_px.json"):
    with open(os.path.join(sd9, n9), "w", encoding="utf-8") as f:
        json.dump({"k": n9}, f)
out9 = ledger_backup.backup_files("20260101", sd9)
chk(all(n9 in out9 for n9 in ("sell_evals.json", "curve_hist_px.json", "futures_px_bybit.json", "daily_px.json")),
    "K9a 받아 둔 보관본·선물 가격 옆 파일 = 원장 밖 사본에 들어감(종전 = 빠짐 → 복구 때 사라짐)", sorted(out9))
os.remove(os.path.join(sd9, "curve_hist_px.json"))
fp9 = ledger_restore.files_plan("20260101", sd9)
rel9 = sorted(r for _s, r in fp9["items"])
chk("curve_hist_px.json" in rel9 and "sell_evals.json" not in rel9 and "futures_px_bybit.json" not in rel9 and "daily_px.json" in rel9
    and any(x.startswith("sell_evals.json") for x in fp9["info"]),
    "K9b 되돌리기 = 보관본은 없을 때만(있으면 그대로 · 안내) · daily_px 등 종전 대상은 늘", {"items": rel9, "info": fp9["info"]})

bd9 = os.path.join(sd9, "backups", "files_20260102")
os.makedirs(bd9, exist_ok=True)
with open(os.path.join(bd9, "sell_evals.json"), "w", encoding="utf-8") as f:
    json.dump({"old": 1}, f)
try:
    fp9c = ledger_restore.files_plan("20260102", sd9)
    ok9c = fp9c["items"] == [] and len(fp9c["info"]) == 1
except SystemExit as e9:
    fp9c, ok9c = str(e9), False
chk(ok9c, "K9c 보관본만 있고 지금 파일도 있음 = 계획 거부 아님(안내만)", fp9c)
os.remove(os.path.join(sd9, "sell_evals.json"))
fp9d = ledger_restore.files_plan("20260102", sd9)
with open(os.path.join(sd9, "sell_evals.json"), "w", encoding="utf-8") as f:
    json.dump({"new": 1}, f)
res9 = ledger_restore.files_apply(fp9d, proc_check=False, state_dir=sd9, log=lambda *a: None)
cur9 = json.load(open(os.path.join(sd9, "sell_evals.json"), encoding="utf-8"))
chk(cur9 == {"new": 1} and "sell_evals.json" not in res9["restored"] and not os.path.exists(os.path.join(sd9, "sell_evals.json.restore_tmp")),
    "K9d 계획 뒤 생긴 보관본 = 적용 때도 덮지 않음", {"cur": cur9, "res": res9["restored"]})
os.remove(os.path.join(sd9, "sell_evals.json"))
res9e = ledger_restore.files_apply(ledger_restore.files_plan("20260102", sd9), proc_check=False, state_dir=sd9, log=lambda *a: None)
chk(json.load(open(os.path.join(sd9, "sell_evals.json"), encoding="utf-8")) == {"old": 1} and res9e["restored"] == ["sell_evals.json"],
    "K9e 없으면 사본으로 되돌림", res9e["restored"])


bd9f = os.path.join(sd9, "backups", "files_20260103")
os.makedirs(bd9f, exist_ok=True)
for n9, v9 in (("att_frozen.json", {"old": 1}), ("daily_px.json", {"old": 1})):
    with open(os.path.join(bd9f, n9), "w", encoding="utf-8") as f:
        json.dump(v9, f)
with open(os.path.join(sd9, "att_frozen.json"), "w", encoding="utf-8") as f:
    json.dump({"new": 1}, f)
fp9f = ledger_restore.files_plan("20260103", sd9)
rel9f = sorted(r for _s, r in fp9f["items"])
res9f = ledger_restore.files_apply(fp9f, proc_check=False, state_dir=sd9, log=lambda *a: None)
cur9f = json.load(open(os.path.join(sd9, "att_frozen.json"), encoding="utf-8"))
chk("att_frozen.json" not in rel9f and "daily_px.json" in rel9f and cur9f == {"new": 1} and any(x.startswith("att_frozen.json") for x in fp9f["info"]),
    "K9f 분해 동결 기록 = 지금 파일 있으면 그대로(안내) · daily_px 는 늘 되돌림", {"items": rel9f, "info": fp9f["info"], "cur": cur9f})
os.remove(os.path.join(sd9, "att_frozen.json"))
res9g = ledger_restore.files_apply(ledger_restore.files_plan("20260103", sd9), proc_check=False, state_dir=sd9, log=lambda *a: None)
chk(json.load(open(os.path.join(sd9, "att_frozen.json"), encoding="utf-8")) == {"old": 1} and "att_frozen.json" in res9g["restored"],
    "K9g 분해 동결 기록이 없으면 사본으로 되돌림", res9g["restored"])

T.finish()
