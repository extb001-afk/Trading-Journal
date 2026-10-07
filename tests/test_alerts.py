#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ["TJ_HEALTH"] = "0"
os.environ["TJ_TG_API"] = "http://127.0.0.1:9/never"
import common

assert T.TMP in common.STATE_DIR
import alert_prefs as AP
import alert_watch as AW
import alert_bot as ab
import health as H

SRC = T.SRC
KST = timezone(timedelta(hours=9))


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


def kst(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=KST).timestamp()


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        return e


try:
    import flowev
except ImportError:
    flowev = None
ab.send_message = lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 발송 금지"))
ab.send_photo = lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 발송 금지"))


REC = AP.preset_doc("rec")
DOC = json.loads(json.dumps(REC))
DOC["th"]["flow_min"] = 10000


def ev_out(i, ts, sym, qty, usd, dst="외부 0x3c7e…cd34", src="Base 지갑 A", cls="external", **kw):
    d = {"id": i, "ts": int(ts), "dir": "out", "cls": cls, "ev": kw.pop("ev", "TRANSFER_OUT"), "basis": kw.pop("basis", "unknown_addr"),
         "sym": sym, "qty": float(qty), "usd": usd, "src": src, "dst": dst, "chain": "base", "tx": "0x" + "ab" * 32, "kind": kw.pop("kind", "")}
    d.update(kw)
    return d


def out_doc(today_iso, rows, built):
    return {"fields": {"rate": 1400.0, "dailySeries": rows, "stables": []}, "todayIso": today_iso, "todayKey": today_iso[5:], "builtAt": int(built)}


def run_flow(st, now, out, events, doc=DOC, on=True):
    inp = {"out": out, "flows": {"v": 1, "builtAt": int(now - 30), "window": 48 * 3600, "ev": events}, "cur": "USD", "pub": ""}
    return safe(AW.prod_bigflow, inp, doc, st, now, None, on)


def kinds(r):
    return [x.get("kind") for x in r] if isinstance(r, list) else [repr(r)]


def texts(r):
    return [x.get("text", "") for x in r] if isinstance(r, list) else [repr(r)]


T1, T2 = kst(2026, 10, 6, 23, 50), kst(2026, 10, 7, 0, 5)
st = {}
run_flow(st, T1, out_doc("2026-10-06", [{"date": "10-06", "flowTop": []}], T1 - 60), [])
e1 = ev_out("o-2359", kst(2026, 10, 6, 23, 59), "USDC", 20000, 20000.0)
r = run_flow(st, T2, out_doc("2026-10-07", [{"date": "10-06", "flowTop": [["외부 전송 USDC", -20000.0]]}, {"date": "10-07", "flowTop": []}], T2 - 60), [e1])
check("R1 23:59 출금이 자정 뒤(00:05) 처음 잡혀도 큰 출금 1통(코인·목적지)", kinds(r) == ["BIG_FLOW"] and "USDC" in texts(r)[0] and "0x3c7e" in texts(r)[0], texts(r))
r = run_flow(st, T2 + 60, out_doc("2026-10-07", [{"date": "10-07", "flowTop": []}], T2), [e1])
check("R1 다음 판·다음 빌드에 같은 출금 = 다시 안 보냄", r == [], texts(r))

T3 = kst(2026, 10, 7, 14, 0)
st = {}
run_flow(st, T3 - 600, out_doc("2026-10-07", [{"date": "10-07", "flowTop": []}], T3 - 700), [])
four = [ev_out("a", T3 - 300, "USDC", 40000, 40000.0, dst="외부 0xaaaa…fa01"), ev_out("b", T3 - 280, "ETH", 10, 30000.0, dst="외부 0xbbbb…fb02"),
        ev_out("c", T3 - 260, "WBTC", 0.3, 20000.0, dst="외부 0xcccc…fc03"), ev_out("d", T3 - 240, "DAI", 11000, 11000.0, dst="외부 0xdddd…fd04")]
top3 = [["외부 전송 USDC", -40000.0], ["외부 전송 ETH", -30000.0], ["외부 전송 WBTC", -20000.0]]
r = run_flow(st, T3, out_doc("2026-10-07", [{"date": "10-07", "flowTop": top3}], T3 - 60), four)
allt = "\n".join(texts(r))
check("R2 출금 4건 = 네 번째(DAI → 0xdddd)까지 코인·목적지 전부 알림", all(s in allt for s in ("USDC", "ETH", "WBTC", "DAI", "0xdddd")), texts(r))
check("R2 큰 출금은 한 통에 묶어 보냄(4건 · 합계)", kinds(r).count("BIG_FLOW") == 1 and "4건" in allt, texts(r))

T4 = kst(2026, 10, 7, 3, 10)
W, W2 = "0x" + "1a" * 20, "0x" + "2b" * 20
G = {1: {"sym": "USDT", "is_stable": True}, 2: {"sym": "USDC", "is_stable": True}, 3: {"sym": "ETH"}}
PX = {3: 2500.0}


def row(pid, ev, sid, ts, loc, qty, gid, ns="base", lk="move_out", sym=None):
    return {"pid": pid, "ns": ns, "sid": sid, "ts": int(ts), "loc": loc, "qty": Decimal(str(qty)), "lk": lk, "ev": ev, "gid": gid, "sym": sym or G[gid]["sym"]}


FP_LABELS = [("거래소 입금 전송", "USDT"), ("브릿지", "USDC"), ("내 지갑 이동", "USDT"), ("거래소 대사 정정", "USDT"), ("마진 부채 반영(차입)", "USDT")]
ts0 = T4 - 600
rows_fp = [
    row(1, "TRANSFER_OUT_EX", "0x" + "e1" * 32, ts0, f"wallet:base:{W}", -20000, 1),
    row(2, "BRIDGE", "0x" + "b1" * 32, ts0, f"wallet:base:{W}", -20000, 2),
    row(3, "TRANSFER_SELF", "0x" + "51" * 32, ts0, f"wallet:base:{W}", -20000, 1),
    row(4, "TRANSFER_SELF", "0x" + "51" * 32, ts0, f"wallet:base:{W2}", 20000, 1, lk="move_in"),
    row(5, "EXF_ADJUST", "exfrecon:USDT", ts0, "exchange:binance", -20000, 1, ns="binance:recon", lk="opening"),
    row(6, "EXF_ADJUST", "exfrecon:USDT2", ts0, "exchange:okx", -20000, 1, ns="okx:recon", lk="opening"),
]
rows_ext = [row(7, "TRANSFER_OUT", "0x" + "f1" * 32, ts0, f"wallet:base:{W}", -20000, 1),
            row(8, "TRANSFER_OUT", "0x" + "f1" * 32, ts0, "out:base:0x" + "9e" * 20, 20000, 1, lk="move_in")]
CL = None
if flowev is not None:
    ctx = flowev._Ctx(G, PX, T4, {"chain": {"base": "Base"}, "wallet": {W: "지갑 A", W2: "지갑 B"}})
    CL = safe(flowev.classify, rows_fp + rows_ext, ctx, debts={"okx:recon": {"USDT": Decimal("-20000")}})
by_ev = {}
for e in (CL if isinstance(CL, list) else []):
    by_ev.setdefault((e["ev"], e["basis"]), []).append(e)
exp = {"거래소 입금 전송": ("TRANSFER_OUT_EX", "internal"), "브릿지": ("BRIDGE", "internal"), "내 지갑 이동": ("TRANSFER_SELF", "internal"),
       "거래소 대사 정정": ("EXF_ADJUST", "adjust"), "마진 부채 반영(차입)": ("EXF_ADJUST", "adjust")}
for lbl, sym in FP_LABELS:
    st = {}
    run_flow(st, T4 - 900, out_doc("2026-10-07", [{"date": "10-07", "flowTop": []}], T4 - 960), [])
    evs = [e for e in (CL if isinstance(CL, list) else []) if e["ev"] == exp[lbl][0] and (lbl != "마진 부채 반영(차입)" or e["basis"] == "debt")
           and (lbl != "거래소 대사 정정" or e["basis"] == "recon")]
    r = run_flow(st, T4, out_doc("2026-10-07", [{"date": "10-07", "flowTop": [[f"{lbl} {sym}", -20000.0]]}], T4 - 60), evs)
    ok_cls = bool(evs) and all(e["cls"] == exp[lbl][1] for e in evs)
    check(f"R3 '{lbl}' = 큰 출금 경보 없음 · 서버 분류 {exp[lbl][1]}" + (" (장부 보정 — 도착/지연도 없음)" if exp[lbl][1] == "adjust" else ""),
          ok_cls and "BIG_FLOW" not in kinds(r) and not any(k in ("MOVE_LATE", "MOVE_SHORT", "MOVE_ARRIVED") for k in kinds(r)) if exp[lbl][1] == "adjust"
          else ok_cls and "BIG_FLOW" not in kinds(r), (kinds(r), [(e["ev"], e["cls"], e["basis"]) for e in evs]))
dbt = by_ev.get(("EXF_ADJUST", "debt"))
if flowev is not None:
    G2 = {k + 100: v for k, v in G.items()}
    rows2 = [dict(r, gid=r["gid"] + 100) for r in rows_fp + rows_ext]
    CL2 = safe(flowev.classify, rows2, flowev._Ctx(G2, {k + 100: v for k, v in PX.items()}, T4, {"chain": {"base": "Base"}}),
               debts={"okx:recon": {"USDT": Decimal("-20000")}})
    ids1 = sorted(e["id"] for e in (CL if isinstance(CL, list) else []))
    ids2 = sorted(e["id"] for e in (CL2 if isinstance(CL2, list) else []))
else:
    ids1, ids2 = [], ["x"]
check("R1 재구축으로 그룹 번호가 바뀌어도 같은 이동 = 같은 id(48시간 안 출금 중복 알림 없음)", ids1 and ids1 == ids2, (ids1[:2], ids2[:2]))
check("R3 차입 부채 반영 = 근거 'debt'(부채 ≈ 정정액) · 대사 정정 = 'recon'", bool(dbt) and bool(by_ev.get(("EXF_ADJUST", "recon"))), list(by_ev))
st = {}
run_flow(st, T4 - 900, out_doc("2026-10-07", [{"date": "10-07", "flowTop": []}], T4 - 960), [])
xe = [e for e in (CL if isinstance(CL, list) else []) if e["ev"] == "TRANSFER_OUT"]
r = run_flow(st, T4, out_doc("2026-10-07", [{"date": "10-07", "flowTop": [["외부 전송 USDT", -20000.0]]}], T4 - 60), xe)
check("R3 모르는 주소 실제 출금 = 서버 external(unknown_addr) · 큰 출금 1통(코인·목적지)", bool(xe) and xe[0]["cls"] == "external" and xe[0]["basis"] == "unknown_addr"
      and kinds(r) == ["BIG_FLOW"] and "USDT" in texts(r)[0] and "0x9e9e" in texts(r)[0], (xe, texts(r)))
check("R3 큰 출금 = 새벽(조용한 시간)에도 바로 · 소리(🔴) · 긴급 종류(URGENT_KINDS)", AP.decide(REC, "bigflow", T4, None, "BIG_FLOW") == "send"
      and AP.in_quiet(REC, T4) and texts(r)[0].startswith("🔴") and not ab._silent_text(texts(r)[0]) and "BIG_FLOW" in AP.URGENT_KINDS, AP.URGENT_KINDS)

T5 = kst(2026, 10, 7, 15, 0)
dep_ok = {"ex": "binance", "uuid": "binance:d1", "txn": "0x" + "c1" * 32, "ts": int(T5 + 420), "amt": "19999.5", "cur": "USDT"}
rows_mv = [row(11, "TRANSFER_OUT_EX", "0x" + "c1" * 32, T5, f"wallet:base:{W}", -20000, 1),
           row(12, "EXF_DEPOSIT", "binance:d1", T5 + 420, "exchange:binance", 19999.5, 1, ns="binance:deposit", lk="move_in"),
           row(13, "BRIDGE", "0x" + "c2" * 32, T5, f"wallet:base:{W}", -8, 3),
           row(14, "TRANSFER_OUT_EX", "0x" + "c3" * 32, T5, f"wallet:base:{W}", -30000, 2),
           row(15, "EXF_DEPOSIT", "okx:d3", T5 + 600, "exchange:okx", 28000, 2, ns="okx:deposit", lk="move_in")]
deps = [dep_ok, {"ex": "okx", "uuid": "okx:d3", "txn": "0x" + "c3" * 32, "ts": int(T5 + 600), "amt": "28000", "cur": "USDC"}]
transit = [{"ex": "upbit", "uuid": "u-1", "ts": int(T5), "start": int(T5 + 60), "qty": Decimal("15000"), "gid": 1, "sym": "USDT", "txid_raw": "0x" + "d1" * 32,
            "state": "pending", "own": True, "cls": "wallet", "dst": "지갑 A", "src": "업비트", "fee": "1"}]
CL4 = safe(flowev.classify, rows_mv, flowev._Ctx(G, PX, T5 + 9000, {"chain": {"base": "Base"}, "wallet": {W: "지갑 A"}}), transit=transit, deps=deps) \
    if flowev is not None else None
E4 = {e["id"]: e for e in (CL4 if isinstance(CL4, list) else [])}


def at(evs, t):
    vs = []
    for e in evs:
        if e["ts"] > t:
            continue
        e2 = dict(e)
        a = e.get("arr")
        if isinstance(a, dict) and a.get("st") == "arrived" and a.get("ts") and a["ts"] > t:
            e2["arr"] = dict(a, st="pending")
        vs.append(e2)
    return vs


evs4 = list(E4.values())
st = {}
run_flow(st, T5 - 60, out_doc("2026-10-07", [], T5 - 120), at(evs4, T5 - 60))
r0 = run_flow(st, T5 + 60, out_doc("2026-10-07", [], T5), at(evs4, T5 + 60))
check("R4 표3-1 내 지갑·거래소·브릿지로 보낼 때 = 알림 없음", isinstance(r0, list) and r0 == [] and len(evs4) >= 4, (texts(r0), len(evs4)))
r1 = run_flow(st, T5 + 480, out_doc("2026-10-07", [], T5 + 450), at(evs4, T5 + 480))
arr1 = [x for x in (r1 if isinstance(r1, list) else []) if x["kind"] == "MOVE_ARRIVED"]
check("R4 표3-1 도착하면 '도착 확인' 1통 = 무음(✅) · 걸린 시간 7분 · 받은 수량 · 수수료로 줄어든 양",
      len(arr1) == 1 and arr1[0]["text"].startswith("✅ USDT 19,999.5개가 바이낸스에 들어왔어요") and "7분" in arr1[0]["text"] and "수수료로 0.5개 줄었어요" in arr1[0]["text"]
      and ab._silent_text(arr1[0]["text"]) and AP.cat_of("MOVE_ARRIVED") == "arrive", texts(r1))
r2 = run_flow(st, T5 + 60 + 1800 + 30, out_doc("2026-10-07", [], T5 + 1850), at(evs4, T5 + 1890))
late = [x for x in (r2 if isinstance(r2, list) else []) if x["kind"] == "MOVE_LATE"]
short = [x for x in (r2 if isinstance(r2, list) else []) if x["kind"] == "MOVE_SHORT"]
check("R4 표3-2 거래소 출금(내 지갑행)이 30분 안에 안 들어옴 = '아직 안 들어왔어요' 소리(🔴) 1통 · 시계 = 거래소가 내보낸 시각부터",
      len(late) == 1 and "업비트에서 출금한 USDT 15,000개가 아직" in late[0]["text"] and late[0]["text"].startswith("🔴"), texts(r2))
check("R4 표3-3 수수료보다 많이 줄어 도착(30,000 → 28,000) = '보낸 것보다 적게 들어왔어요' 소리 1통",
      len(short) == 1 and short[0]["text"].startswith("🔴 보낸 것보다 적게 들어왔어요") and "28,000개 받음" in short[0]["text"], texts(r2))
r3 = run_flow(st, T5 + 3000, out_doc("2026-10-07", [], T5 + 2950), at(evs4, T5 + 3000))
check("R4 브릿지는 2시간 전엔 '늦음' 없음(일반 30분과 다른 기준)", isinstance(r3, list) and not any("브릿지" in t for t in texts(r3)), texts(r3))
r4 = run_flow(st, T5 + 7200 + 60, out_doc("2026-10-07", [], T5 + 7200), at(evs4, T5 + 7260))
check("R4 표3-2 브릿지 2시간 지나도 안 들어옴 = '2시간 전 브릿지로 보낸 ETH 8개가 아직…' 소리 1통 · 같은 건 다시 안 보냄",
      [x["kind"] for x in (r4 if isinstance(r4, list) else [])] == ["MOVE_LATE"] and "브릿지로 보낸 ETH 8개가 아직" in texts(r4)[0], texts(r4))
r5 = run_flow(st, T5 + 9000, out_doc("2026-10-07", [], T5 + 8990), at(evs4, T5 + 9000))
check("R4 늦음·적게·도착은 건마다 한 번 — 다음 판 0통", r5 == [], texts(r5))
d_off = json.loads(json.dumps(DOC))
d_off["cats"]["arrive"] = "off"
st = {}
run_flow(st, T5 - 60, out_doc("2026-10-07", [], T5 - 120), at(evs4, T5 - 60), doc=d_off)
ro = run_flow(st, T5 + 1900, out_doc("2026-10-07", [], T5 + 1890), at(evs4, T5 + 1900), doc=d_off)
check("R4 도착 확인(arrive)만 꺼도 늦음·적게(소리)는 그대로 · 도착 확인은 안 옴", isinstance(ro, list) and "MOVE_ARRIVED" not in kinds(ro)
      and "MOVE_SHORT" in kinds(ro) and "MOVE_LATE" in kinds(ro), kinds(ro))
st = {}
run_flow(st, T5 - 60, out_doc("2026-10-07", [], T5 - 120), at(evs4, T5 - 60), on=False)
rb = run_flow(st, T5 + 1900, out_doc("2026-10-07", [], T5 + 1890), at(evs4, T5 + 1900), on=False)
check("R4 큰 출금을 끄고 도착 확인만 켜면 = 소리 알림 0 · 적게 들어온 건 도착 확인(무음)에 '수수료보다 … 더'",
      isinstance(rb, list) and set(kinds(rb)) == {"MOVE_ARRIVED"} and any("수수료보다 1,818개 더" in t for t in texts(rb)), texts(rb))
check("R4 도착 확인 = 별도 카테고리(즉시·무음) · 추천 켬 · 최소 끔 · 문장에 내부 용어 없음",
      AP.TIER.get("arrive") == "now" and REC["cats"].get("arrive") == "on" and AP.preset_doc("min")["cats"].get("arrive") == "off"
      and not any(j in t for t in texts(r1) + texts(r2) + texts(r4) for j in AP.JARGON), (AP.TIER.get("arrive"), REC["cats"].get("arrive")))
mn = dict(AP.preset_doc("min")["cats"])
mn.pop("arrive", None)
check("R4 저장값에 arrive 칸이 없을 때 = 나머지가 최소면 끔·추천이면 켬(프리셋 일치 유지)",
      AP.normalize({"v": 2, "cats": mn})["cats"].get("arrive") == "off" and AP.match_preset({"v": 2, "cats": mn}) == "min"
      and AP.normalize({"v": 2, "cats": {k: v for k, v in REC["cats"].items() if k != "arrive"}})["cats"].get("arrive") == "on", mn)

T6 = kst(2026, 10, 8, 10, 0)
st = {}
run_flow(st, T6 - 600, out_doc("2026-10-08", [], T6 - 660), [])
sm = [ev_out(f"s{i}", T6 - 500 + i * 10, sym, 4000, 4000.0, dst=f"외부 0x{i}{i}{i}…") for i, sym in enumerate(("USDC", "ETH", "SOL"))]
ra = run_flow(st, T6 - 300, out_doc("2026-10-08", [], T6 - 320), sm[:2])
rb2 = run_flow(st, T6, out_doc("2026-10-08", [], T6 - 20), sm)
check("R4 작은 출금이 모여 24시간 합계가 기준을 넘으면 한 통(코인 셋 전부)", ra == [] and kinds(rb2) == ["BIG_FLOW"]
      and all(s in texts(rb2)[0] for s in ("USDC", "ETH", "SOL")), (texts(ra), texts(rb2)))

lines = [(i + 1, {"kind": "BIG_FLOW", "text": f"🔴 {s} {q}개(−${u:,})가 밖으로 나갔어요 → 외부 0x{h}…{h}\n내가 한 게 아니면 바로 거래소·지갑 보안을 확인하세요.\nBase 지갑 A · 03:1{i}"})
         for i, (s, q, u, h) in enumerate((("USDC", "40,000", 40000, "aaaa"), ("ETH", "10", 30000, "bbbb"), ("WBTC", "0.3", 20000, "cccc"), ("DAI", "11,000", 11000, "dddd")))]
cm = ab.coalesce_k(lines)
mt = cm[0][1] if cm else ""
check("R5 출금 4건이 한꺼번에 = 한 통에 4건 전부(코인·목적지) — 네 번째(DAI → 0xdddd) 안 버림", len(cm) == 1 and all(s in mt for s in ("USDC", "ETH", "WBTC", "DAI", "0xaaaa", "0xdddd"))
      and mt.startswith("🔴") and len(cm[0][3]) == 4, mt)
big = [(i + 1, {"kind": "DEPEG", "text": f"🔴 X{i} 스테이블 코인 시세가 1달러에서 5% 벗어났어요\n보유 비중을 확인하세요.\n" + "현재 " + "9" * 300}) for i in range(30)]
cb = ab.coalesce_k(big)
cbt = "\n".join(m9[1] for m9 in cb)
check("R5 아주 많으면 글자 수 상한 안에서 여러 통으로 이어서 — 30건 전부 · 통마다 3,900자 이하 · '외 N건' 없음",
      len(cb) >= 2 and all(len(m9[1]) <= 3900 for m9 in cb) and all(f"X{i} " in cbt for i in range(30)) and "외 " not in cbt
      and all(m9[0] is None for m9 in cb[:-1]) and cb[-1][0] is not None and len(cb[-1][3]) == 30
      and sorted(o9 for m9 in cb[:-1] for o9 in m9[3]) == sorted(set(o9 for m9 in cb[:-1] for o9 in m9[3])),
      [(m9[0], len(m9[1]), len(m9[3])) for m9 in cb])

pt = H.plain_text("외부 탐색기(블록스카웃) 장애 — base.blockscout.com 응답 없음 · state/ext_rederive_queue.json 대기 · 미정산 펀딩 2건 · 잔고 대사 · https://base.blockscout.com/tx/0xAbC")
check("R6 base.blockscout.com 보존", pt.count("base.blockscout.com") == 2, pt)
check("R6 ext_rederive_queue.json(경로) 보존", "state/ext_rederive_queue.json" in pt and "ext_다시" not in pt, pt)
check("R6 '미정산' 뜻 유지(미마감 아님 → '확정 전')", "미마감" not in pt and "확정 전 펀딩" in pt, pt)
check("R6 URL·주소 보존 + 나머지 내부 용어는 그대로 바꿈(잔고 대사 → 잔고 맞추기 · 블록스카웃 중복 없음)", "https://base.blockscout.com/tx/0xAbC" in pt and "잔고 맞추기" in pt
      and "블록스카웃" not in pt and "외부 탐색기(외부 탐색기)" not in pt, pt)
check("R6 영문 밑줄 식별자 단독(ext_rederive_queue)도 보존 · 옆 낱말은 바꿈", H.plain_text("ext_rederive_queue 커서") == "ext_rederive_queue 진행 위치",
      H.plain_text("ext_rederive_queue 커서"))

HS = H.settings({})
_l0 = AP.load
AP.load = lambda prefs=None: AP.preset_doc("rec")


def ckh(level, cid, title, unit, kind, persist=0, resolve=0):
    return {"id": cid, "unit": unit, "title": title, "level": level, "detail": "자세히", "action": "x", "since": None, "persist": persist, "resolve": resolve,
            "notify": True, "remind": True, "kind": kind, "suppressed": None}


sent = []


def fsend(text, reply_to=None):
    sent.append(text)
    return True, len(sent), None


T7 = kst(2026, 10, 7, 13, 0)
s9 = {}
for k9 in range(6):
    t9 = T7 + k9 * 60
    H.plan(s9, H.step(s9, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
H.deliver(s9, fsend, T7 + 400, HS)
check("R7 디스크 가득(저절로 안 풀림) = '대부분 저절로 풀려요' 아님 · 공간 비우라는 할 일", len(sent) == 1 and "대부분 저절로 풀려요" not in sent[0]
      and "디스크 공간을 비워" in sent[0], sent)
for k9 in range(1, 31 * 6):
    t9 = T7 + 400 + k9 * 600
    H.plan(s9, H.step(s9, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s9, fsend, t9 + 1, HS)
snd = [x for x in sent if not x.startswith("📋")]
check("R8 30시간 이어지면 = 1시간 뒤 한 번만 다시(🔴 아직 안 풀렸어요) — 그 뒤 조용(소리 알림 총 2통)", len(snd) == 2 and snd[1].startswith("🔴 아직 안 풀렸어요 · 디스크 여유 부족"), sent)
sent.clear()
s9 = {}
for k9 in range(6):
    t9 = T7 + k9 * 60
    H.plan(s9, H.step(s9, [ckh("crit", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain")], t9, HS), t9, HS, True)
H.deliver(s9, fsend, T7 + 400, HS)
check("R7 외부 탐색기 지연(저절로 풀리는 종류) = '대부분 저절로 풀려요 — 한 시간 넘게…한 번 더'", len(sent) == 1 and "대부분 저절로 풀려요" in sent[0] and "한 번 더" in sent[0], sent)
sent.clear()
s9 = {}
t9 = T7
end = T7 + 43 * 60
while t9 < end:
    lvl = "crit" if ((t9 - T7) // 60) % 9 < 6 else "ok"
    H.plan(s9, H.step(s9, [ckh(lvl, "proc:tj-web", "프로세스 상태", "tj-web", "proc", persist=300, resolve=60)], t9, HS), t9, HS, True)
    H.deliver(s9, fsend, t9 + 1, HS)
    t9 += 60
n43 = len(sent)
for k9 in range(25):
    H.plan(s9, H.step(s9, [ckh("ok", "proc:tj-web", "프로세스 상태", "tj-web", "proc", persist=300, resolve=60)], t9, HS), t9, HS, True)
    H.deliver(s9, fsend, t9 + 1, HS)
    t9 += 60
check("R9 6분 나쁨·3분 정상 43분 = 1통(생김) · 안정된 뒤 풀림 1통 = 문제당 두 통", n43 == 1 and len(sent) == 2 and sent[1].startswith("✅ 풀렸어요"), (n43, sent))
AP.load = _l0

D9 = kst(2026, 10, 7, 9, 5)
hd = ab.load_hold()
for ex in ("binance", "okx", "gate"):
    ab.dg_add(hd, None, None, "recon", "EXF_RECON", f"{ex} 잔고 대사 완료 — 4개 통화 보정", D9 - 3600)
txt = ab.compose_digest(hd["dg"], REC, D9, None, {})[0] or ""
check("R10 12개를 맞춘 날 = '잔고 맞춤: 12개 고침'('모두 맞아요' 아님)", "잔고 맞춤: 12개 고침" in txt and "모두 맞아요" not in txt, txt)
h0 = ab.load_hold()
ab.dg_add(h0, None, None, "recon", "RECON", "[base] 기초잔고 대사 완료 — 0개 자산 보정", D9 - 3600)
t0 = ab.compose_digest(h0["dg"], REC, D9, None, {})[0] or ""
check("R10 고친 게 0이면 그때만 '잔고는 모두 맞아요'", "잔고는 모두 맞아요" in t0 and "고침" not in t0, t0)
for _i in range(ab.DG_ITEMS_MAX + 30):
    ab.dg_add(hd, None, None, "scam", "UNKNOWN", "처음 보는 토큰", D9 - 60)
t1 = ab.compose_digest(hd["dg"], REC, D9, None, {})[0] or ""
check("R10 재료가 상한에서 밀려나도 고친 수는 남음", "잔고 맞춤: 12개 고침" in t1, t1)

N1 = kst(2026, 10, 7, 3, 30)


def dp_out(stables):
    return {"fields": {"stables": stables, "rate": 1400.0}}


def quotes(sym, px, exs, age, t):
    return {f"{e}:{sym}": px for e in exs}, {f"{e}:{sym}": t - age for e in exs}


st = {"depeg": {"DAI": {"at": int(N1 - 30 * 86400), "px": 0.988, "dev": 1.2}}}
safe(AW.prod_depeg, {"out": dp_out([]), "spot": {"ex_usd": {}, "ex_ts": {}}}, REC, st, N1, None, True)
q2, t2q = quotes("DAI", 0.985, ("binance", "bybit", "okx"), 30, N1 + 7 * 86400)
r = safe(AW.prod_depeg, {"out": dp_out([{"sym": "DAI", "qty": 20000.0, "price": 0.985}]), "spot": {"ex_usd": q2, "ex_ts": t2q}}, REC, st, N1 + 7 * 86400, None, True)
check("R11 판 코인의 옛 기억이 지워져 다시 사서 1.5% 벗어나면 알림(옛 1.2%의 두 배 규칙에 안 묻힘)", kinds(r) == ["DEPEG"] and "DAI" in texts(r)[0], (texts(r), st.get("depeg")))
st = {}
q3, t3q = quotes("USDC", 0.985, ("binance",), 28 * 60, N1)
r = safe(AW.prod_depeg, {"out": dp_out([]), "spot": {"ex_usd": q3, "ex_ts": t3q}}, REC, st, N1, None, True)
check("R11 보유하지 않은 코인 · 거래소 한 곳 28분 전 시세 = 새벽 알림 없음", r == [], texts(r))
r = safe(AW.prod_depeg, {"out": dp_out([{"sym": "USDC", "qty": 50000.0, "price": 1.0}]), "spot": {"ex_usd": q3, "ex_ts": t3q}}, REC, {}, N1, None, True)
check("R11 들고 있어도 낡은(28분) 한 곳 시세만으론 알림 없음", r == [], texts(r))
q4, t4q = quotes("USDC", 0.985, ("binance", "okx"), 60, N1)
r = safe(AW.prod_depeg, {"out": dp_out([{"sym": "USDC", "qty": 50000.0, "price": 1.0}]), "spot": {"ex_usd": q4, "ex_ts": t4q}}, REC, {}, N1, None, True)
check("R11 들고 있는 코인 · 신선한 두 곳 시세로 1.5% 이탈 = 알림(밤에도)", kinds(r) == ["DEPEG"] and AP.decide(REC, "depeg", N1, None, "DEPEG") == "send", texts(r))

app = open(os.path.join(T.ROOT, "web", "v2", "app.js"), encoding="utf-8").read()
hjs = open(os.path.join(T.ROOT, "web", "v2", "health.js"), encoding="utf-8").read()
rd = open(T.README, encoding="utf-8").read()
check("R12 이전 배너: 옛 '추천'의 급등락 꺼짐 · 조용한 시간에도 목표가·디페그·큰 출금이 바로", "급등락 알림은 이제 꺼져 있어요" in app
      and "조용한 시간에도 목표가·손절, 스테이블 가격 이탈, 내가 안 한 큰 출금은 이제 바로 와요" in app and "almig" in app)
check("R12 상태 패널 '6시간마다 리마인드' 없음", "6시간마다 리마인드" not in hjs)
check("R12 README '처음 7일' 동작 없음 · 조용한 시간 = 급등락만", "처음 7일은 동기화" not in rd and "급등락만 모았다가" in rd)

wsrc = open(os.path.join(SRC, "web.py"), encoding="utf-8").read()
check("R13 빌드가 재료(flowev.collect)를 만들고 감시기 입력에 'flows'로 넘김(화면 게시본엔 안 실음)", "self._flow_ev = flowev.collect(" in wsrc
      and '"flows": b9.__dict__.get("_flow_ev")' in wsrc and '"flowEv"' not in wsrc)
check("R13 큰 출금·도착 확인이 켜져 있으면 낡은 빌드(5분+ · 입력 바뀜)에 백그라운드 재빌드 1번(기다리지 않음)", "_flow_fresh_kick(now)" in wsrc and "def _flow_fresh_kick" in wsrc)
check("R13 거래소 출금 판정에 수수료(fee) 실음", '"fee": p.get("fee")' in wsrc)

T8 = kst(2026, 10, 8, 14, 0)
CTX8 = flowev._Ctx(G, PX, T8, {"chain": {"base": "Base"}, "wallet": {W: "지갑 A"}}) if flowev is not None else None


def cls_of(rows=(), **kw):
    if flowev is None:
        return None
    r = safe(flowev.classify, list(rows), CTX8, **kw)
    return r if isinstance(r, list) else None


wu = [{"ex": "binance", "uuid": "binance:w9", "ts": int(T8 - 600), "start": int(T8 - 600), "qty": Decimal("30000"), "gid": 1, "sym": "USDT",
       "txid_raw": "0x" + "a9" * 32, "state": "pending", "own": False, "cls": "wallet_untracked", "addr": "0x" + "2b" * 20, "dst": "지갑 B", "src": "바이낸스"}]
c14 = cls_of(transit=wu) or []
check("R14 미추적 네트워크의 내 지갑 출금 = internal(도착 확인 불가 none) · 큰 출금 아님",
      len(c14) == 1 and c14[0]["cls"] == "internal" and (c14[0].get("arr") or {}).get("st") == "none", c14)
r15 = [row(81, "TRANSFER_OUT", "0x" + "81" * 32, T8 - 300, f"wallet:base:{W}", -25000, 1),
       row(82, "TRANSFER_OUT", "0x" + "81" * 32, T8 - 300, "out:base:0x" + "77" * 20, 25000, 1, lk="move_in"),
       row(83, "TRANSFER_OUT", "0x" + "83" * 32, T8 - 200, f"wallet:base:{W}", -25000, 2),
       row(84, "TRANSFER_OUT", "0x" + "83" * 32, T8 - 200, "out:base:0x" + "77" * 20, 25000, 2, lk="move_in")]
c15 = cls_of(r15, of_rows=[{"address": "0x" + "77" * 20, "status": "external", "verdict": "external", "txs": [], "tokens": []}],
             of_match={82: {"basis": "amount_time", "ex": "binance", "uuid": "binance:d82", "cur": "USDT"}},
             of_bridge={84: {"key": 999, "chain": "arbitrum", "ts": int(T8 - 100), "sym": "USDC", "qty": 24990}}) or []
c15w = cls_of(transit=[dict(wu[0], uuid="binance:w15", cls=None, own=False, verdict="external", state="arrived", arr_ts=int(T8 - 60))]) or []
check("R15 외부 판정 주소로 보낸 출금 = 자동 매칭(거래소 금액·시간 / 브릿지)이 있어도 external(verdict)",
      len(c15) == 2 and all(e["cls"] == "external" and e["basis"] == "verdict:external" for e in c15), [(e["cls"], e["basis"]) for e in c15])
check("R15 거래소 출금도 받는 주소 외부 판정 = 도착 표시보다 먼저 external", len(c15w) == 1 and c15w[0]["cls"] == "external", c15w)
r16 = [row(91, "TRANSFER_OUT", "0x" + "91" * 32, T8 - 300, f"wallet:base:{W}", -20000, 1),
       row(92, "TRANSFER_OUT", "0x" + "91" * 32, T8 - 300, "out:base:0x" + "66" * 20, 20000, 1, lk="move_in")]
old_ret = {"address": "0x" + "66" * 20, "status": "returned", "txs": [], "tokens": [],
           "returned": [{"ts": int(T8 - 30 * 86400), "usd": 130000.0, "sym": "USDT", "qty": 130000.0}]}
c16 = cls_of(r16, of_rows=[old_ret]) or []
new_ret = dict(old_ret, returned=[{"ts": int(T8 - 100), "usd": 20000.0, "sym": "USDT", "qty": 20000.0}] + old_ret["returned"])
c16b = cls_of(r16, of_rows=[new_ret]) or []
check("R16 과거에 많이 돌려받은 주소로 새 20,000 출금 = external(큰 출금 대상)", len(c16) == 1 and c16[0]["cls"] == "external", c16)
check("R16 그 송금 뒤 전액 돌아왔으면 = ignore(되돌려 받음)", len(c16b) == 1 and c16b[0]["cls"] == "ignore", c16b)
for nm, bad in (("seen 값 정수", {"flow2": {"init": 1, "seen": {"broken": 1}}}), ("seen None", {"flow2": {"init": 1, "seen": None}}),
                ("flow2 목록", {"flow2": []})):
    st = json.loads(json.dumps(bad))
    ev17 = ev_out("n17", T8 - 60, "USDC", 30000, 30000.0)
    r = run_flow(st, T8, out_doc("2026-10-08", [], T8 - 30), [ev17])
    if nm == "seen 값 정수":
        check(f"R17 손상 기억({nm}) = 예외 없이 큰 출금 1통 · 손상 칸 정리", isinstance(r, list) and kinds(r) == ["BIG_FLOW"]
              and "broken" not in (st.get("flow2") or {}).get("seen", {}), (r, st))
    else:
        r2 = run_flow(st, T8 + 60, out_doc("2026-10-08", [], T8 + 30), [ev17, ev_out("n17b", T8 + 30, "ETH", 12, 30000.0)])
        check(f"R17 손상 기억({nm}) = 예외 없이 다시 쌓고 다음 새 출금은 알림", isinstance(r, list) and isinstance(r2, list) and kinds(r2) == ["BIG_FLOW"]
              and "ETH" in texts(r2)[0], (r, r2))
st = {"flow2": {"init": 1, "seen": {}}}
_q0 = flowev.short_of if flowev is not None else None
if flowev is not None:
    flowev.short_of = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("중간 예외(시험)"))
ev17i = ev_out("i17", T8 - 4000, "USDT", 20000, 20000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_txid", kind="exchange",
               arr={"st": "arrived", "ts": int(T8 - 3500), "qty": 20000.0, "exp": 1800})
r = run_flow(st, T8, out_doc("2026-10-08", [], T8 - 30), [ev_out("x17", T8 - 50, "USDC", 30000, 30000.0), ev17i])
if flowev is not None:
    flowev.short_of = _q0
r2 = run_flow(st, T8 + 60, out_doc("2026-10-08", [], T8 + 30), [ev_out("x17", T8 - 50, "USDC", 30000, 30000.0), ev17i])
check("R17 판 도중 예외 = 기억을 판 전으로 되돌림 → 다음 판에 그 출금 알림(영구 유실 없음)", isinstance(r, Exception) and "BIG_FLOW" in kinds(r2), (r, r2))
r18 = [row(101, "EXF_DEPOSIT", "binance:d1x", T8 - 200, "exchange:binance", 30000, 2, ns="binance:deposit", lk="move_in"),
       row(102, "EXF_DEPOSIT", "binance:d2x", T8 - 190, "exchange:binance", 20000, 2, ns="binance:deposit", lk="move_in")]
c18 = cls_of(r18, of_match={555: {"basis": "hop_split", "ex": "binance", "uuid": None, "uuids": ["binance:d1x", "binance:d2x"]}}) or []
check("R18 경유 분할 입금 = internal(deposit_match)", len(c18) == 2 and all(e["cls"] == "internal" for e in c18), [(e["cls"], e["basis"]) for e in c18])
long_dst = "외부 0x" + "ab" * 20 + " (" + "경유 설명 " * 120 + ") 끝목적지XYZ"
l19 = [(1, {"kind": "BIG_FLOW", "text": f"🔴 USDC 1개(−$1)가 밖으로 나갔어요 → {long_dst}\n할 일\nBase 지갑 A · 03:10"})] + \
      [(i, {"kind": "BIG_FLOW", "text": f"🔴 C{i} 1개가 밖으로 나갔어요 → 외부 0x{i}\n할 일\n03:1{i}"}) for i in range(2, 5)]
c19 = ab.coalesce_k(l19)
check("R19 800자 항목도 3,400자 안이면 끝(목적지)까지 그대로", len(c19) == 1 and "끝목적지XYZ" in c19[0][1] and "외 " not in c19[0][1], c19[0][1][-200:] if c19 else c19)
q20 = {f"binance:{s9}": 1.05 for s9 in ("USDC", "USD1", "FDUSD")}
r = safe(AW.prod_depeg, {"out": {"fields": {"stables": [{"sym": "USDT", "qty": 9000.0, "price": 1.0}]}},
                          "spot": {"ex_usd": q20, "ex_ts": {k: T8 - 30 for k in q20}}}, REC, {}, T8, None, True)
check("R20 USDT 보유 · 거래소 한 곳의 다른 스테이블 1.05 = USDT 디페그 없음", r == [], texts(r))
q20b = {f"{e9}:{s9}": 1.05 for e9 in ("binance", "okx") for s9 in ("USDC", "USD1", "FDUSD")}
r = safe(AW.prod_depeg, {"out": {"fields": {"stables": [{"sym": "USDT", "qty": 9000.0, "price": 1.0}]}},
                          "spot": {"ex_usd": q20b, "ex_ts": {k: T8 - 30 for k in q20b}}}, REC, {}, T8, None, True)
check("R20 두 곳 이상이면 USDT 디페그 1통", kinds(r) == ["DEPEG"] and "USDT" in texts(r)[0], texts(r))
AP.load = lambda prefs=None: AP.preset_doc("rec")
sent.clear()
s21 = {}
t9 = T8
for k9 in range(5):
    H.plan(s21, H.step(s21, [ckh("crit", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain", persist=120)], t9, HS), t9, HS, True)
    H.deliver(s21, fsend, t9 + 1, HS)
    t9 += 60
for k9 in range(3):
    H.plan(s21, H.step(s21, [ckh("ok", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain", persist=120)], t9, HS), t9, HS, True)
    H.deliver(s21, fsend, t9 + 1, HS)
    t9 += 60
h0 = float(((s21.get("res_hold") or {}).get("sync:chain:base") or {}).get("at") or t9)
t9 = h0 + 60
while t9 < h0 + 840:
    H.plan(s21, H.step(s21, [ckh("ok", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain", persist=120)], t9, HS), t9, HS, True)
    H.deliver(s21, fsend, t9 + 1, HS)
    t9 += 60
for k9 in range(6):
    H.plan(s21, H.step(s21, [ckh("crit", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain", persist=120)], t9, HS), t9, HS, True)
    H.deliver(s21, fsend, t9 + 1, HS)
    t9 += 60
check("R21 보류 끝무렵 재발 = '풀렸어요'·새 '발생' 없음(같은 사건 이어감)", len(sent) == 1 and not any(x.startswith("✅") for x in sent), sent)
sent.clear()
s22 = {}
t9 = T8
for k9 in range(5):
    H.plan(s22, H.step(s22, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    t9 += 60
H.deliver(s22, fsend, t9, HS)
fails = lambda text, reply_to=None: (False, None, "down")
for k9 in range(26):
    t9 += 3600
    H.plan(s22, H.step(s22, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s22, fails, t9 + 1, HS)
for k9 in range(3):
    t9 += 600
    H.plan(s22, H.step(s22, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s22, fsend, t9 + 1, HS)
snd22 = [x for x in sent if not x.startswith("📋")]
check("R22 리마인드가 하루 넘게 못 나가 버려져도 다시 1통(아직 열린 빨강)", len(snd22) == 2 and snd22[1].startswith("🔴 아직 안 풀렸어요"), sent)
HS6 = H.settings({"health": {"remind_hours": 6}})
sent.clear()
s23 = {}
t9 = T8
for k9 in range(5):
    H.plan(s23, H.step(s23, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS6), t9, HS6, True)
    t9 += 60
for k9 in range(30 * 6):
    t9 += 600
    H.plan(s23, H.step(s23, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS6), t9, HS6, True)
    H.deliver(s23, fsend, t9 + 1, HS6)
snd23 = [x for x in sent if not x.startswith("📋")]
check("R23 remind_hours=6 저장값 + 새 1시간 한 번 = 30시간 동안 소리 2통(발생+1회)", len(snd23) == 2, snd23)
AP.load = _l0

T9 = kst(2026, 10, 9, 14, 0)
c26 = cls_of(transit=[dict(wu[0], uuid="binance:w26", cls=None, own=False, verdict=None, state="arrived", why="amount", arr_ts=int(T8 - 60))]) or []
c26b = cls_of([row(261, "TRANSFER_IN", wu[0]["txid_raw"], T8 - 60, f"wallet:arbitrum:{wu[0]['addr']}", 30000, 1, ns="arbitrum", lk="acq")],
              transit=[dict(wu[0], uuid="binance:w26b", cls=None, own=False, verdict=None, state="arrived", why=None, arr_ts=int(T8 - 60))]) or []
c26b = [e for e in c26b if e["ev"] == "EXF_WITHDRAW"]
check("R26 모르는 주소로 나간 거래소 출금 + 같은 수량 입금 우연 일치(금액 안전망) = external(큰 출금)", len(c26) == 1 and c26[0]["cls"] == "external", c26)
check("R26 txid 로 도착 확인된 출금은 그대로 internal", len(c26b) == 1 and c26b[0]["cls"] == "internal", c26b)
st = {}
run_flow(st, T9 - 600, out_doc("2026-10-09", [], T9 - 660), [])
e27i = ev_out("m27", T9 - 500, "USDC", 20000, 20000.0, cls="internal", basis="deposit_amount_time", kind="exchange", arr={"st": "pending", "exp": 1800})
r = run_flow(st, T9 - 300, out_doc("2026-10-09", [], T9 - 320), [e27i])
e27x = dict(e27i, cls="external", basis="unknown_addr")
e27x.pop("arr")
r2 = run_flow(st, T9 - 200, out_doc("2026-10-09", [], T9 - 220), [e27x])
r3 = run_flow(st, T9 - 100, out_doc("2026-10-09", [], T9 - 120), [e27x])
check("R27 내 이동으로 먼저 본 출금이 외부로 정정되면 = 그때 큰 출금 1통(한 번만)", r == [] and kinds(r2) == ["BIG_FLOW"] and r3 == [], (texts(r), texts(r2), texts(r3)))
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [])
six = [ev_out(f"q{i}", T9 - 800 + i * 100, "USDC", 6000, 6000.0, dst=f"외부 0xq{i}") for i in range(4)]
rs = [run_flow(st, T9 - 750 + i * 100, out_doc("2026-10-09", [], T9 - 760 + i * 100), six[:i + 1]) for i in range(4)]
ids = [x.get("ids") for r9 in rs if isinstance(r9, list) for x in r9 if x.get("kind") == "BIG_FLOW"]
check("R28 $6,000 네 건(기준 $1만) = 둘째에 [q0,q1] · 넷째에 [q2,q3] — 이미 알린 건 반복 없음", ids == [["q1", "q0"], ["q3", "q2"]] or ids == [["q0", "q1"], ["q2", "q3"]]
      or [sorted(x) for x in ids] == [["q0", "q1"], ["q2", "q3"]], ids)
d28 = json.loads(json.dumps(DOC))
d28["cats"]["bigflow"] = "off"
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [], doc=d28, on=False)
off9 = ev_out("off9", T9 - 800, "USDC", 9000, 9000.0)
run_flow(st, T9 - 700, out_doc("2026-10-09", [], T9 - 720), [off9], doc=d28, on=False)
run_flow(st, T9 - 600, out_doc("2026-10-09", [], T9 - 620), [off9])
r = run_flow(st, T9 - 500, out_doc("2026-10-09", [], T9 - 520), [off9, ev_out("on1k", T9 - 550, "ETH", 1, 1000.0)])
check("R28 꺼 둔 동안의 $9,000 + 다시 켠 뒤 $1,000 = 합계 알림 없음(꺼진 동안 것 안 실음)", r == [], texts(r))
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [], doc=d28, on=False)
run_flow(st, T9 - 600, out_doc("2026-10-09", [], T9 - 660), [], doc=d28, on=False)
late29 = ev_out("late29", T9 - 500, "USDC", 30000, 30000.0)
r = run_flow(st, T9 - 300, out_doc("2026-10-09", [], T9 - 320), [])
r2 = run_flow(st, T9 - 200, out_doc("2026-10-09", [], T9 - 220), [late29])
r3 = run_flow(st, T9 - 100, out_doc("2026-10-09", [], T9 - 120), [late29, ev_out("new29", T9 - 150, "ETH", 10, 25000.0)])
check("R29 꺼진 동안 생긴 출금 = 다시 켠 뒤 처음 보여도 몰려오지 않음 · 다시 켠 뒤 새 출금은 1통", r == [] and r2 == [] and kinds(r3) == ["BIG_FLOW"]
      and "ETH" in texts(r3)[0] and "USDC" not in texts(r3)[0], (texts(r), texts(r2), texts(r3)))
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [])
arr4 = [ev_out(f"a{i}", T9 - 800, "USDT", 20000, 20000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_txid", kind="exchange", src="Base 지갑 A",
               arr={"st": "arrived", "ts": int(T9 - 800 + 420), "qty": 19999.5, "where": "바이낸스", "exp": 1800}) for i in range(4)]
r = run_flow(st, T9 - 300, out_doc("2026-10-09", [], T9 - 320), arr4) or []
L30 = (texts(r)[0] if r and isinstance(r, list) else "").split("\n")
c30 = ab.coalesce_k([(i + 1, x) for i, x in enumerate(r if isinstance(r, list) else [])])
check("R30 도착 확인 = 첫 줄 무슨 일 · 둘째 줄 할 일 · 셋째 줄 걸린 시간·수수료", len(L30) == 3 and L30[1] == "할 일은 없어요." and "7분" in L30[2] and "수수료로 0.5개" in L30[2], L30)
check("R30 도착 확인 넷이 묶여도 걸린 시간·수수료 그대로", len(c30) == 1 and c30[0][1].count("7분") == 4 and c30[0][1].count("수수료로 0.5개") == 4, c30[0][1] if c30 else c30)
AP.load = lambda prefs=None: AP.preset_doc("rec")
sent.clear()
s31 = {}
t9 = T9
for k9 in range(5):
    H.plan(s31, H.step(s31, [ckh("crit", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain")], t9, HS), t9, HS, True)
    H.deliver(s31, fsend, t9 + 1, HS)
    t9 += 60
for k9 in range(3):
    H.plan(s31, H.step(s31, [ckh("ok", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain")], t9, HS), t9, HS, True)
    H.deliver(s31, fsend, t9 + 1, HS)
    t9 += 60
for k9 in range(20):
    H.plan(s31, H.step(s31, [ckh(None, "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain")], t9, HS), t9, HS, True)
    H.deliver(s31, fsend, t9 + 1, HS)
    t9 += 60
n31 = len(sent)
for k9 in range(17):
    H.plan(s31, H.step(s31, [ckh("ok", "sync:chain:base", "Base 수집 멈춤", "tj-evm", "chain")], t9, HS), t9, HS, True)
    H.deliver(s31, fsend, t9 + 1, HS)
    t9 += 60
check("R31 보류 중 판단 보류 20분 = '풀렸어요' 없음 · 그 뒤 정상 15분 이어지면 풀림 1통", n31 == 1 and len(sent) == 2 and sent[1].startswith("✅ 풀렸어요"), (n31, sent))
AP.load = _l0
T10 = kst(2026, 10, 10, 14, 0)
G10 = dict(G)
G10.update({7: {"sym": "USDC"}, 8: {"sym": "SCAM1"}})
CTX10 = flowev._Ctx(G10, PX, T10, {"chain": {"base": "Base", "arbitrum": "Arbitrum"}}, skip_gids={7}) if flowev is not None else None


def cls10(rows=(), **kw):
    if flowev is None:
        return None
    r = safe(flowev.classify, list(rows), CTX10, **kw)
    return r if isinstance(r, list) else None


br = [row(201, "BRIDGE", "0x" + "c9" * 32, T10 - 600, f"wallet:base:{W}", -20000, 2)]
fake_in = [row(202, "TRANSFER_IN", "0x" + "d9" * 32, T10 - 300, f"wallet:arbitrum:{W}", 20000, 7, ns="arbitrum", lk="acq", sym="USDC"),
           row(203, "TRANSFER_IN", "0x" + "da" * 32, T10 - 200, f"wallet:arbitrum:{W}", 20000, 8, ns="arbitrum", lk="acq", sym="USDC")]
c32 = cls10(br + fake_in) or []
b32 = [e for e in c32 if e["ev"] == "BRIDGE"]
check("R32 격리된 사칭 USDC·원시 심볼만 USDC 인 유입 = 브릿지 도착 아님(pending)", len(b32) == 1 and (b32[0].get("arr") or {}).get("st") == "pending", b32)
wd32 = [{"ex": "binance", "uuid": "binance:w32", "ts": int(T10 - 900), "start": int(T10 - 900), "qty": Decimal("20000"), "gid": 2, "sym": "USDC",
         "txid_raw": "0x" + "d9" * 32, "state": "arrived", "own": True, "cls": "wallet", "dst": "지갑 A", "src": "바이낸스", "arr_ts": int(T10 - 300)}]
c32w = cls10(fake_in, transit=wd32) or []
w32 = [e for e in c32w if e["ev"] == "EXF_WITHDRAW"]
check("R32 거래소 출금 '받은 수량'에 격리 유입을 안 셈", len(w32) == 1 and (w32[0].get("arr") or {}).get("qty") is None, w32)
DA, DB = "0x" + "aa" * 20, "0x" + "bb" * 20
mt = [row(211, "TRANSFER_OUT", "0x" + "e7" * 32, T10 - 500, f"wallet:base:{W}", -20000, 2),
      row(212, "TRANSFER_OUT", "0x" + "e7" * 32, T10 - 500, f"out:base:{DA}", 20000, 2, lk="move_in"),
      row(213, "TRANSFER_OUT", "0x" + "e7" * 32, T10 - 500, f"wallet:base:{W}", -8, 3),
      row(214, "TRANSFER_OUT", "0x" + "e7" * 32, T10 - 500, f"out:base:{DB}", 8, 3, lk="move_in")]
om33 = {212: {"basis": "txid", "ex": "binance", "uuid": "binance:d33", "cur": "USDC"}, 214: {"basis": "txid", "ex": "binance", "uuid": None, "cur": "USDC"}}
dp33 = [{"ex": "binance", "uuid": "binance:d33", "txn": "0x" + "e7" * 32, "ts": int(T10 - 400), "amt": "20000", "cur": "USDC"}]
c33 = cls10(mt, of_match=om33, deps=dp33, of_rows=[{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []},
                                                     {"address": DB, "status": "pending", "txs": [], "tokens": []}]) or []
e33 = {e["sym"]: e for e in c33 if e["ev"] == "TRANSFER_OUT"}
check("R33 한 tx: USDC → 내 거래소(입금 확인) · ETH → 모르는 주소 = USDC internal · ETH external(큰 출금)",
      (e33.get("USDC") or {}).get("cls") == "internal" and (e33.get("ETH") or {}).get("cls") == "external", [(k, v["cls"], v["basis"]) for k, v in e33.items()])
c33x = cls10(mt, of_match=om33, deps=dp33, of_rows=[{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []},
                                                      {"address": DB, "status": "exchange_matched", "txs": [], "tokens": []}]) or []
check("R33 같은 종류: 리플레이가 그 수령처 행을 '거래소 매칭'으로 둬도(같은 tx 다른 자산 입금뿐) = ETH external",
      [e["cls"] for e in c33x if e["ev"] == "TRANSFER_OUT" and e["sym"] == "ETH"] == ["external"], [(e["sym"], e["cls"], e["basis"]) for e in c33x])
mt2 = mt[:3] + [row(214, "TRANSFER_OUT", "0x" + "e7" * 32, T10 - 500, f"out:base:{DA}", 8, 3, lk="move_in")]
c33b = cls10(mt2, of_match=om33, deps=dp33, of_rows=[{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []}]) or []
check("R33 같은 수령처(입금 확인된 주소)로 간 다른 자산 레그 = internal", [e["cls"] for e in c33b if e["ev"] == "TRANSFER_OUT"] == ["internal", "internal"],
      [(e["sym"], e["cls"], e["basis"]) for e in c33b])
amb = [row(221, "TRANSFER_IN", "0x" + "f1" * 32, T10 - 400, f"wallet:arbitrum:{W}", 12000, 2, ns="arbitrum", lk="acq"),
       row(222, "TRANSFER_IN", "0x" + "f2" * 32, T10 - 300, f"wallet:arbitrum:{W}", 20000, 2, ns="arbitrum", lk="acq")]
c34 = [e for e in (cls10(br + amb) or []) if e["ev"] == "BRIDGE"]
check("R34 브릿지 도착 후보 둘 = 확정 안 함(도착 확인 불가 none · 적게/늦음 경보 없음)", len(c34) == 1 and (c34[0].get("arr") or {}).get("st") == "none", c34)
one = [row(222, "TRANSFER_IN", "0x" + "f2" * 32, T10 - 300, f"wallet:arbitrum:{W}", 19990, 2, ns="arbitrum", lk="acq")]
c34b = [e for e in (cls10(br + one) or []) if e["ev"] == "BRIDGE"]
check("R34 후보 하나 = 도착(19,990)", len(c34b) == 1 and (c34b[0].get("arr") or {}).get("st") == "arrived" and abs((c34b[0]["arr"].get("qty") or 0) - 19990) < 1e-6, c34b)
st = {}
run_flow(st, T10 - 900, out_doc("2026-10-10", [], T10 - 960), [])
safe(AW.prod_bigflow, {"out": out_doc("2026-10-10", [], T10 - 960), "flows": None, "cur": "USD"}, d28, st, T10 - 800, None, False)
late35 = ev_out("late35", T10 - 700, "USDC", 30000, 30000.0)
r = run_flow(st, T10 - 400, out_doc("2026-10-10", [], T10 - 420), [late35])
check("R35 재료 없는 판에 끈 것도 기억 — 다시 켠 뒤 꺼진 동안 출금 몰려오지 않음", r == [], texts(r))
st = {}
run_flow(st, T10 - 900, out_doc("2026-10-10", [], T10 - 960), [])
r = run_flow(st, T10 - 300, out_doc("2026-10-10", [], T10 - 320), [ev_out("big36", T10 - 350, "USDC", 20000, 20000.0),
                                                                 ev_out("tiny36", T10 - 340, "ETH", 0.02, 50.0, dst="외부 0xtiny…0036")])
check("R36 큰 출금 + $50 출금 = 둘 다 줄로(소액 생략 없음)", kinds(r) == ["BIG_FLOW"] and "ETH 0.02개" in texts(r)[0] and "0xtiny" in texts(r)[0] and "소액" not in texts(r)[0], texts(r))
AP.load = lambda prefs=None: AP.preset_doc("rec")
sent.clear()
s37 = {}
t9 = T10
for k9 in range(6):
    H.plan(s37, H.step(s37, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s37, fsend, t9 + 1, HS)
    t9 += 60
c37 = None
while c37 is None or t9 < c37 + 86400 - 400:
    H.plan(s37, H.step(s37, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s37, fails, t9 + 1, HS)
    c37 = c37 or next((o["created"] for o in s37.get("outbox") or [] if o.get("kind") == "remind"), None)
    t9 += 600
t9 = c37 + 86400 - 300
while t9 < c37 + 86400 + 120:
    H.plan(s37, H.step(s37, [ckh("ok", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s37, fails, t9 + 1, HS)
    t9 += 60
held37 = "disk:state" in (s37.get("res_hold") or {}) and not any(o.get("kind") == "remind" for o in s37.get("outbox") or [])
for k9 in range(6):
    H.plan(s37, H.step(s37, [ckh("crit", "disk:state", "디스크 여유 부족", "system", "disk")], t9, HS), t9, HS, True)
    H.deliver(s37, fsend, t9 + 1, HS)
    t9 += 60
snd37 = [x for x in sent if not x.startswith("📋")]
check("R37 보류 중 버려진 리마인드 = 재개 뒤 1통(유실 없음)", held37 and len(snd37) == 2 and snd37[1].startswith("🔴 아직 안 풀렸어요"), (held37, sent))
AP.load = _l0
T11 = kst(2026, 10, 11, 14, 0)
for qa, qb in ((20000, 30000), (1000, 20000)):
    mt38 = [row(301, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 500, f"wallet:base:{W}", -(qa + qb), 2),
            row(302, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 500, f"out:base:{DA}", qa, 2, lk="move_in"),
            row(303, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 500, f"out:base:{DB}", qb, 2, lk="move_in")]
    om38 = {302: {"basis": "txid", "ex": "binance", "uuid": "binance:d38", "cur": "USDC"}, 303: {"basis": "txid", "ex": "binance", "uuid": "binance:d38", "cur": "USDC"}}
    dp38 = [{"ex": "binance", "uuid": "binance:d38", "txn": "0x" + "38" * 32, "ts": int(T10 - 400), "amt": str(qa), "cur": "USDC"}]
    for stb in ("pending", "exchange_matched"):
        c38 = cls10(mt38, of_match=om38, deps=dp38, of_rows=[{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []},
                                                             {"address": DB, "status": stb, "txs": [], "tokens": []}]) or []
        r38 = {e["dst"][-4:] if e["dst"] else "": e["cls"] for e in c38 if e["ev"] == "TRANSFER_OUT"}
        cA = [e["cls"] for e in c38 if e["ev"] == "TRANSFER_OUT" and abs(e["qty"] - qa) < 1e-9]
        cB = [e["cls"] for e in c38 if e["ev"] == "TRANSFER_OUT" and abs(e["qty"] - qb) < 1e-9]
        check(f"R38 한 tx USDC {qa:,}→내 거래소 · {qb:,}→모르는 주소({stb}) · 입금 {qa:,} 한 건 = 앞 internal · 뒤 external", cA == ["internal"] and cB == ["external"],
              [(e["qty"], e["cls"], e["basis"]) for e in c38])
oth = [row(311, "TRANSFER_IN", "0x" + "39" * 32, T10 - 300, f"wallet:arbitrum:{W}", 5, 3, ns="arbitrum", lk="acq"),
       row(312, "TRANSFER_IN", "0x" + "39" * 32, T10 - 300, f"wallet:arbitrum:{W}", 20000, 7, ns="arbitrum", lk="acq", sym="USDC")]
w39 = dict(wd32[0], uuid="binance:w39", txid_raw="0x" + "39" * 32)
c39o = [e for e in (cls10(oth, transit=[w39]) or []) if e["ev"] == "EXF_WITHDRAW"]
c39x = [e for e in (cls10(oth, transit=[dict(w39, own=False, cls=None, addr="0x" + "9e" * 20, dst=None)]) or []) if e["ev"] == "EXF_WITHDRAW"]
check("R39 내 지갑행 출금 · 다른 자산·격리 유입뿐 = internal pending(늦음 감시) — 도착 확인 아님", len(c39o) == 1 and c39o[0]["cls"] == "internal"
      and (c39o[0].get("arr") or {}).get("st") == "pending", c39o)
check("R39 모르는 주소 출금 · 다른 자산·격리 유입뿐 = external(큰 출금)", len(c39x) == 1 and c39x[0]["cls"] == "external", c39x)
mt40 = [row(321, "TRANSFER_OUT", "0x" + "40" * 32, T10 - 500, f"wallet:base:{W}", -20000, 2),
        row(322, "TRANSFER_OUT", "0x" + "40" * 32, T10 - 500, f"out:base:{DB}", 20000, 2, lk="move_in")]
ob40 = {322: {"key": 999, "gid": 7, "chain": "arbitrum", "ts": int(T10 - 300), "sym": "USDC", "qty": 20000}}
c40k = [e for e in (cls10(mt40, of_bridge=ob40, of_rows=[{"address": DB, "status": "bridge_matched", "bridge": {"name": "브릿지X"}, "txs": [], "tokens": []}]) or [])
        if e["ev"] == "TRANSFER_OUT"]
c40u = [e for e in (cls10(mt40, of_bridge=ob40, of_rows=[{"address": DB, "status": "bridge_matched", "txs": [], "tokens": []}]) or []) if e["ev"] == "TRANSFER_OUT"]
check("R40 알려진 브릿지 · 유효 도착 없음 = internal pending(늦음 감시)", len(c40k) == 1 and c40k[0]["cls"] == "internal" and (c40k[0].get("arr") or {}).get("st") == "pending", c40k)
check("R40 브릿지 라벨 없는 수령처 · 유효 도착 없음 = external", len(c40u) == 1 and c40u[0]["cls"] == "external", c40u)
dep41 = [row(331, "EXF_DEPOSIT", "okx:d41a", T10 - 300, "exchange:okx", 10000, 2, ns="okx:deposit", lk="move_in"),
         row(332, "EXF_DEPOSIT", "okx:d41b", T10 - 290, "exchange:okx", 10000, 2, ns="okx:deposit", lk="move_in")]
w41 = dict(wd32[0], uuid="binance:w41", txid_raw="", txid="amt:x", gid=2, sym="USDC", own=True, cls="exchange", state="arrived", arr_ts=int(T10 - 290))
c41 = [e for e in (cls10(dep41, transit=[w41], xf_links={"okx:d41a": {"wd_uuid": "binance:w41"}, "okx:d41b": {"wd_uuid": "binance:w41"}}) or [])
       if e["ev"] == "EXF_WITHDRAW"]
check("R41 분할 입금 둘 다 더함 = 받은 20,000", len(c41) == 1 and abs(((c41[0].get("arr") or {}).get("qty") or 0) - 20000) < 1e-6, c41)
st = {}
run_flow(st, T11 - 900, out_doc("2026-10-11", [], T11 - 960), [])
e21 = [ev_out(f"b{i:02d}", T11 - 800 + i, "USDC", 20000 - i, float(20000 - i), dst=f"외부 0xfa{i:02x}") for i in range(21)]
r1 = run_flow(st, T11 - 600, out_doc("2026-10-11", [], T11 - 620), e21) or []
r2 = run_flow(st, T11 - 540, out_doc("2026-10-11", [], T11 - 560), e21) or []
r3 = run_flow(st, T11 - 480, out_doc("2026-10-11", [], T11 - 500), e21) or []
check("R42 21건 = 첫 통 20줄('외 1건') · 다음 판에 21번째(0xfa14)를 이어서 1통 · 그 뒤 0통", kinds(r1) == ["BIG_FLOW"] and "외 1건" in texts(r1)[0]
      and "0xfa14" not in texts(r1)[0] and kinds(r2) == ["BIG_FLOW"] and "0xfa14" in texts(r2)[0] and r3 == [], (texts(r1)[:1], texts(r2), texts(r3)))
d45 = json.loads(json.dumps(DOC))
d45["cats"]["bigflow"] = "off"
d45["cats"]["arrive"] = "off"
st = {}
run_flow(st, T11 - 9000, out_doc("2026-10-11", [], T11 - 9060), [], doc=d45, on=False)
run_flow(st, T11 - 8000, out_doc("2026-10-11", [], T11 - 8060), [], doc=d45, on=False)
mv45 = [ev_out("sh45", T11 - 7000, "USDT", 30000, 30000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_txid", kind="exchange",
               arr={"st": "arrived", "ts": int(T11 - 6800), "qty": 28000.0, "where": "OKX", "exp": 1800}),
        ev_out("lt45", T11 - 7000, "USDT", 30000, 30000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_addr", kind="exchange",
               arr={"st": "pending", "exp": 1800}),
        ev_out("ok45", T11 - 7000, "USDT", 30000, 30000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_txid", kind="exchange",
               arr={"st": "arrived", "ts": int(T11 - 6900), "qty": 30000.0, "where": "OKX", "exp": 1800}),
        dict(ev_out("in45", T11 - 7000, "ETH", 12, 30000.0), dir="in", ev="TRANSFER_IN", basis="unknown_in")]
run_flow(st, T11 - 600, out_doc("2026-10-11", [], T11 - 620), [])
r45 = run_flow(st, T11 - 500, out_doc("2026-10-11", [], T11 - 520), mv45)
check("R45 꺼진 동안 일어난 부족 도착·늦음·큰 입금·도착 확인 = 다시 켠 뒤 알림 없음", r45 == [], texts(r45))
def wd10(**kw):
    d = {"ex": "binance", "uuid": "binance:w48", "ts": int(T10 - 900), "start": int(T10 - 900), "qty": Decimal("30000"), "gid": 2, "sym": "USDC",
         "txid_raw": "0x" + "48" * 32, "state": "arrived", "own": False, "cls": None, "addr": DB, "dst": None, "src": "바이낸스", "arr_ts": int(T10 - 300)}
    d.update(kw)
    return d


def wd_of(evs):
    return [e for e in (evs or []) if e["ev"] == "EXF_WITHDRAW"]


def to_of(evs, qty=None):
    return [e for e in (evs or []) if e["ev"] == "TRANSFER_OUT" and (qty is None or abs(e["qty"] - qty) < 1e-9)]


mt46 = [row(301, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 5000, f"wallet:base:{W}", -50000, 2),
               row(302, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 5000, f"out:base:{DA}", 20000, 2, lk="move_in"),
               row(303, "TRANSFER_OUT", "0x" + "38" * 32, T10 - 5000, f"out:base:{DB}", 30000, 2, lk="move_in")]
later46 = [row(401, "TRANSFER_OUT", "0x" + "46" * 32, T10 - 600, f"wallet:base:{W}", -40000, 2),
           row(402, "TRANSFER_OUT", "0x" + "46" * 32, T10 - 600, f"out:base:{DB}", 40000, 2, lk="move_in")]
om46 = {302: {"basis": "txid", "ex": "binance", "uuid": "binance:d38", "cur": "USDC"}, 303: {"basis": "txid", "ex": "binance", "uuid": "binance:d38", "cur": "USDC"},
        402: {"basis": "address", "ex": "binance", "uuid": None, "cur": "USDC", "dt": None, "how": "txid"}}
dp46 = [{"ex": "binance", "uuid": "binance:d38", "txn": "0x" + "38" * 32, "ts": int(T10 - 4900), "amt": "20000", "cur": "USDC"}]
rw46 = [{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []}, {"address": DB, "status": "exchange_matched", "txs": [], "tokens": []}]
c46 = to_of(cls10(mt46 + later46, of_match=om46, deps=dp46, of_rows=rw46), 40000)
check("R46 잘못 입증된 입금주소(같은 tx 외부 수령처) → 뒤 40,000 출금 = external(큰 출금)", [e["cls"] for e in c46] == ["external"], c46)
ps46 = [{"pid": 501, "txn": "0x" + "51" * 32, "chain": "base", "dest": DA, "sym": "USDC", "qty": Decimal("20000")}]
om46b = {501: {"basis": "txid", "ex": "binance", "uuid": "binance:d51", "cur": "USDC"}, 412: {"basis": "address", "ex": "binance", "uuid": None, "cur": "USDC", "how": "txid"}}
dp46b = [{"ex": "binance", "uuid": "binance:d51", "txn": "0x" + "51" * 32, "ts": int(T10 - 30 * 86400), "amt": "19999", "cur": "USDC"}]
r46b = [row(411, "TRANSFER_OUT", "0x" + "41" * 32, T10 - 600, f"wallet:base:{W}", -25000, 2),
        row(412, "TRANSFER_OUT", "0x" + "41" * 32, T10 - 600, f"out:base:{DA}", 25000, 2, lk="move_in")]
rw46b = [{"address": DA, "status": "exchange_matched", "txs": [], "tokens": []}]
c46b = to_of(cls10(r46b, of_match=om46b, deps=dp46b, of_rows=rw46b, proof_sends=ps46))
c46n = to_of(cls10(r46b, of_match=om46b, deps=dp46b, of_rows=rw46b))
check("R46 창 밖의 단일 수령처 R1 레그로 입증된 입금주소(보낸 내역 전체) = internal · 그 증거를 못 보면(창 안만) external(안전한 쪽)",
      [e["cls"] for e in c46b] == ["internal"] and [e["cls"] for e in c46n] == ["external"], (c46b, c46n))
om46l = {**om46, 402: dict(om46[402], how="list")}
c46l = to_of(cls10(mt46 + later46, of_match=om46l, deps=dp46, of_rows=rw46), 40000)
c46h = to_of(cls10(mt46 + later46, of_match=om46, deps=dp46, of_rows=rw46, deposit_exchange=lambda ch, a: "binance" if a == DB else None), 40000)
check("R46 거래소 API·설정 목록의 입금주소(how list · 목록 조회 훅) = internal", [e["cls"] for e in c46l] == ["internal"] and [e["cls"] for e in c46h] == ["internal"],
      (c46l, c46h))
r47 = [row(421, "TRANSFER_OUT", "0x" + "47" * 32, T10 - 900, f"wallet:base:{W}", -25000, 2),
       row(422, "TRANSFER_OUT", "0x" + "47" * 32, T10 - 900, f"out:base:{DB}", 25000, 2, lk="move_in"),
       row(423, "EXF_DEPOSIT", "binance:d47", T10 - 600, "exchange:binance", 24990, 2, ns="binance:deposit", lk="move_in")]
om47 = {422: {"basis": "amount_time", "ex": "binance", "uuid": "binance:d47", "cur": "USDC", "dt": 300}}
for orig, want, win in ((None, "external", "external"), (DB, "internal", "internal")):
    dp47 = [{"ex": "binance", "uuid": "binance:d47", "txn": "0x" + "77" * 32, "ts": int(T10 - 600), "amt": "24990", "cur": "USDC", "origin_from": orig}]
    c47 = cls10(r47, of_match=om47, deps=dp47, of_rows=[{"address": DB, "status": "exchange_matched", "txs": [], "tokens": []}]) or []
    o47, i47 = to_of(c47), [e for e in c47 if e["ev"] == "EXF_DEPOSIT"]
    check(f"R47 금액·시간 짝 · 입금 발신지 {'모름' if orig is None else '= 수령처'} = 출금 {want} · 입금 {win}",
          [e["cls"] for e in o47] == [want] and [e["cls"] for e in i47] == [win]
          and (want == "external" or ((o47[0].get("arr") or {}).get("st") == "arrived" and abs((o47[0]["arr"].get("qty") or 0) - 24990) < 1e-6)), c47)
in48W = [row(431, "TRANSFER_IN", "0x" + "48" * 32, T10 - 300, f"wallet:base:{W}", 30000, 2, lk="acq")]
in48W2 = [row(432, "TRANSFER_IN", "0x" + "48" * 32, T10 - 300, f"wallet:base:{W2}", 30000, 2, lk="acq")]
c48a = cls10(in48W, transit=[wd10()]) or []
check("R48 모르는 주소 B 로 출금 · 같은 배치 tx 에서 내 지갑 A 가 같은 코인 받음 = external(큰 출금) · A 유입은 내 이동 아님",
      [e["cls"] for e in wd_of(c48a)] == ["external"] and [e["cls"] for e in c48a if e["ev"] == "TRANSFER_IN"] == ["external"], c48a)
c48b = wd_of(cls10(in48W, transit=[wd10(addr=W2, own=True, cls="wallet", dst="지갑 B")]))
c48c = wd_of(cls10(in48W2, transit=[wd10(addr=W2, own=True, cls="wallet", dst="지갑 B")]))
check("R48 내 지갑 B 로 출금 · 유입은 지갑 A 에만 = internal pending(늦음 감시) · 지갑 B 로 들어옴 = 도착 30,000",
      [e["cls"] for e in c48b] == ["internal"] and (c48b[0].get("arr") or {}).get("st") == "pending"
      and (c48c[0].get("arr") or {}).get("st") == "arrived" and abs((c48c[0]["arr"].get("qty") or 0) - 30000) < 1e-6, (c48b, c48c))
dep48 = [row(433, "EXF_DEPOSIT", "okx:d48", T10 - 300, "exchange:okx", 29990, 2, ns="okx:deposit", lk="move_in")]
w48l = wd10(txid_raw="", txid="amt:x")
c48amt = wd_of(cls10(dep48, transit=[w48l], xf_links={"okx:d48": {"wd_uuid": "binance:w48", "rule": "amt"}}))
c48spl = wd_of(cls10(dep48, transit=[w48l], xf_links={"okx:d48": {"wd_uuid": "binance:w48", "rule": "split"}}))
c48hop = wd_of(cls10(dep48, transit=[w48l], xf_links={"okx:d48": {"wd_uuid": "binance:w48", "rule": "hop", "via": DB}}))
check("R48 모르는 주소 출금 + 거래소 간 금액·분할 연결뿐 = external · 그 주소에서 온 경유(hop) 연결 = internal 도착",
      [e["cls"] for e in c48amt] == ["external"] and [e["cls"] for e in c48spl] == ["external"]
      and [e["cls"] for e in c48hop] == ["internal"] and (c48hop[0].get("arr") or {}).get("st") == "arrived", (c48amt, c48spl, c48hop))
dpt48 = [{"ex": "okx", "uuid": "okx:d48", "txn": "0x" + "48" * 32, "ts": int(T10 - 300), "amt": "29990", "cur": "USDC"}]
c48d = wd_of(cls10(dep48, transit=[wd10()], deps=dpt48))
c48e = wd_of(cls10(dep48, transit=[wd10(own=True, cls="exchange", dst="OKX")], deps=dpt48))
check("R48 모르는 주소 출금 + 같은 txid 거래소 입금 = external · 받는 주소가 내 거래소 입금주소 = internal 도착",
      [e["cls"] for e in c48d] == ["external"] and [e["cls"] for e in c48e] == ["internal"] and (c48e[0].get("arr") or {}).get("st") == "arrived", (c48d, c48e))
c48f = wd_of(cls10(dep48, transit=[wd10(txid_raw="", txid="amt:x", addr=W2, own=False, cls="wallet_untracked", dst="지갑 B")],
                   xf_links={"okx:d48": {"wd_uuid": "binance:w48", "rule": "split"}}))
check("R48 받는 주소가 이미 내 것(미추적 네트워크의 내 지갑) = 분할 연결은 도착 수량 근거로(내 이동 · 도착 29,990)",
      [e["cls"] for e in c48f] == ["internal"] and (c48f[0].get("arr") or {}).get("st") == "arrived" and abs((c48f[0]["arr"].get("qty") or 0) - 29990) < 1e-6, c48f)
G48 = {**G10, 9: {"sym": "TKN"}}
CTX48 = flowev._Ctx(G48, PX, T10, {"chain": {"base": "Base"}}, skip_gids={7}) if flowev is not None else None
w48a = wd10(sym="TKN1", gid=None, qty=Decimal("5000"), own=True, cls="exchange", dst="업비트")
dp48a = [{"ex": "upbit", "uuid": "upbit:d48a", "txn": "0x" + "48" * 32, "ts": int(T10 - 300), "amt": "5000", "cur": "TKN"}]
c48g = wd_of(safe(flowev.classify, [], CTX48, transit=[w48a], deps=dp48a) if flowev is not None else None)
c48h = wd_of(safe(flowev.classify, [], CTX48, transit=[w48a], deps=[dict(dp48a[0], amt="3000")]) if flowev is not None else None)
check("R48 내 거래소 입금주소로 출금 · 같은 txid 입금 하나 · 수량 일치 · 표기만 다름(TKN1↔TKN) = 도착 · 수량 다르면 도착 아님(늦음 감시)",
      (c48g[0].get("arr") or {}).get("st") == "arrived" and (c48h[0].get("arr") or {}).get("st") == "pending", (c48g, c48h))
c48i = wd_of(cls10([], transit=[wd10(addr="", own=False, cls=None, why="amount", uuid="binance:w48i")]))
check("R48 받는 주소 기록 없는 출금(업비트·빗썸) + 금액·시간 안전망 '도착' = 도착 확정 안 함(늦음 감시 pending)",
      [e["cls"] for e in c48i] == ["internal"] and (c48i[0].get("arr") or {}).get("st") == "pending", c48i)
r49 = [row(441, "TRANSFER_OUT", "0x" + "49" * 32, T10 - 900, f"wallet:base:{W}", -30000, 2),
       row(442, "TRANSFER_OUT", "0x" + "49" * 32, T10 - 900, f"out:base:{DB}", 30000, 2, lk="move_in")]
om49 = {442: {"basis": "hop_split", "ex": "binance", "uuid": None, "uuids": ["binance:h1", "binance:h2"], "cur": "USDC"}}
dp49 = [{"ex": "binance", "uuid": "binance:h1", "txn": "0x" + "a1" * 32, "ts": int(T10 - 500), "amt": "20000", "cur": "USDC", "origin_from": DB},
        {"ex": "binance", "uuid": "binance:h2", "txn": "0x" + "a2" * 32, "ts": int(T10 - 400), "amt": "9990", "cur": "USDC", "origin_from": DB}]
c49 = to_of(cls10(r49, of_match=om49, deps=dp49))
check("R49 경유 분할 입금 도착 = 마지막 입금 시각 · 수량 합 29,990", len(c49) == 1 and (c49[0].get("arr") or {}).get("ts") == int(T10 - 400)
      and abs((c49[0]["arr"].get("qty") or 0) - 29990) < 1e-6, c49)
d49 = json.loads(json.dumps(DOC))
d49["cats"]["arrive"] = "off"
st = {}
run_flow(st, T11 - 9000, out_doc("2026-10-11", [], T11 - 9060), [], doc=d49)
run_flow(st, T11 - 8000, out_doc("2026-10-11", [], T11 - 8060), [], doc=d49)
run_flow(st, T11 - 600, out_doc("2026-10-11", [], T11 - 620), [])
nt49 = ev_out("nt49", T11 - 7000, "USDC", 30000, 30000.0, cls="internal", ev="TRANSFER_OUT", basis="deposit_hop_split", kind="exchange",
              arr={"st": "arrived", "ts": None, "qty": None, "where": "바이낸스", "exp": 1800})
r49a = run_flow(st, T11 - 500, out_doc("2026-10-11", [], T11 - 520), [nt49])
nt49b = dict(nt49, id="nt49b", ts=int(T11 - 450))
r49b = run_flow(st, T11 - 400, out_doc("2026-10-11", [], T11 - 420), [nt49, nt49b])
check("R49 도착 시각 모름 · 꺼진 동안 보낸 것 = 다시 켠 뒤 도착 확인 없음 · 켠 뒤 보낸 것 = 1통(받은 수량은 앱에서)",
      r49a == [] and kinds(r49b) == ["MOVE_ARRIVED"] and "앱에서 확인" in texts(r49b)[0], (texts(r49a), texts(r49b)))
al50 = [row(451, "TRANSFER_IN", "0x" + "50" * 32, T10 - 300, f"wallet:arbitrum:{W}", 12000, 2, ns="arbitrum", lk="acq", sym="LEGACYUSD")]
c50 = [e for e in (cls10(br + al50) or []) if e["ev"] == "BRIDGE"]
st = {}
run_flow(st, T10 - 900, out_doc("2026-10-10", [], T10 - 960), [])
r50 = run_flow(st, T10 - 200, out_doc("2026-10-10", [], T10 - 220), c50)
check("R50 브릿지 20,000 → 같은 그룹(원시 심볼 별칭) 12,000 도착 = 도착 심볼 USDC · 적게 들어옴(MOVE_SHORT) 1통",
      len(c50) == 1 and (c50[0].get("arr") or {}).get("sym") == "USDC" and kinds(r50) == ["MOVE_SHORT"], (c50, texts(r50)))
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [])
sh51 = [ev_out(f"sh{i}", T9 - 800, "USDT", 30000, 30000.0, cls="internal", ev="TRANSFER_OUT_EX", basis="deposit_txid", kind="exchange", src=f"Base 지갑 S{i}",
               arr={"st": "arrived", "ts": int(T9 - 600), "qty": 28000.0 - i * 100, "where": f"거래소 R{i}", "exp": 1800}) for i in range(4)]
r51 = run_flow(st, T9 - 300, out_doc("2026-10-09", [], T9 - 320), sh51) or []
c51 = ab.coalesce_k([(i + 1, x) for i, x in enumerate(r51 if isinstance(r51, list) else [])])
t51 = c51[0][1] if c51 else ""
check("R51 부족 도착 4건 묶음 = 건마다 '보낸 곳 → 받은 곳'·'수수료보다 … 더'·'확인' 남음", kinds(r51) == ["MOVE_SHORT"] * 4 and len(c51) == 1
      and all(f"Base 지갑 S{i} → 거래소 R{i}" in t51 for i in range(4)) and t51.count("수수료보다") == 4 and t51.count("확인하세요") >= 4, t51)
st = {}
run_flow(st, T9 - 900, out_doc("2026-10-09", [], T9 - 960), [], on=False)
r51b = run_flow(st, T9 - 300, out_doc("2026-10-09", [], T9 - 320), sh51, on=False) or []
c51b = ab.coalesce_k([(i + 1, x) for i, x in enumerate(r51b if isinstance(r51b, list) else [])])
t51b = c51b[0][1] if c51b else ""
check("R51 큰 출금을 끄고 부족 도착 4건(도착 확인) 묶음 = '할 일은 없어요'로 바뀌지 않고 '내역을 확인하세요' 남음",
      kinds(r51b) == ["MOVE_ARRIVED"] * 4 and len(c51b) == 1 and "할 일은 없어요" not in t51b and "내역을 확인하세요" in t51b and t51b.count("수수료보다") == 4, t51b)
qpath = os.path.join(common.STATE_DIR, "alerts_web.jsonl")
with open(qpath, "w", encoding="utf-8") as f9:
    for i in range(30):
        f9.write(json.dumps({"kind": "DEPEG", "text": f"🔴 Y{i:02d} 스테이블 코인 시세가 1달러에서 5% 벗어났어요\n보유 비중을 확인하세요.\n" + "현재 " + "8" * 300}, ensure_ascii=False) + "\n")
sent52, fail52 = [], [False]


def _snd52(tok, chat, text):
    if fail52[0] and sent52:
        return False
    sent52.append(text)
    return True


_s0, _sl0 = ab.send, ab.time.sleep
ab.send, ab.time.sleep = _snd52, (lambda *_a: None)
ab._SENT_TIMES[:] = []
cur52, st52, hold52 = {"alerts_web.jsonl": 0}, ab.load_stats(), ab.load_hold()
fail52[0] = True
safe(ab.run_source, "alerts_web.jsonl", "t", "c", cur52, AP.preset_doc("rec"), None, st52, hold52, {})
n1_52, cur1_52 = len(sent52), cur52.get("alerts_web.jsonl")
fail52[0] = False
safe(ab.run_source, "alerts_web.jsonl", "t", "c", cur52, AP.preset_doc("rec"), None, st52, hold52, {})
safe(ab.run_source, "alerts_web.jsonl", "t", "c", cur52, AP.preset_doc("rec"), None, st52, hold52, {})
ab.send, ab.time.sleep = _s0, _sl0
all52 = "\n".join(sent52)
check("R52 상한 넘는 묶음 = 첫 통만 나가고 실패 → 커서 그대로 · 다음 판에 남은 통만 → 30건 각각 정확히 한 번 · '외 N건' 없음",
      n1_52 == 1 and cur1_52 == 0 and len(sent52) >= 2 and all(all52.count(f"Y{i:02d} ") == 1 for i in range(30)) and "외 " not in all52
      and cur52.get("alerts_web.jsonl") == os.path.getsize(qpath), (n1_52, cur1_52, len(sent52), [len(x) for x in sent52], cur52))

json.dump({"chains": {}, "wallets": [], "web": {"port": 1}}, open(os.path.join(T.TMP, "config.json"), "w"))
try:
    import web
except Exception as e9:
    web = None
    print("web 가져오기 실패:", e9)
if web is not None:
    class FB:
        def __init__(self):
            self.prefs_doc = {"plans": {}, "alert_prefs": DOC}
            self._flow_ev = None
            self._last_out = {"fields": {"rate": 1400.0, "stables": []}, "builtAt": int(T8)}
            self.kicks = 0
            self.sig, self._built_sig = "a", "a"
            self.snaps = type("S", (), {"cur": type("C", (), {"at": T8 - 400})()})()

        def prefs(self):
            return self.prefs_doc

        def inputs_changed(self, snap=None, now=None):
            return True

        def _input_sig(self):
            return self.sig

        def kick_refresh(self):
            self.kicks += 1
    fb = FB()
    web.BUILDER = fb
    conn_ok = [True]
    web._tg_connected = lambda: conn_ok[0]
    web._append_alert = lambda a9: None
    wst = {}
    fl = lambda t, evs: {"v": 1, "builtAt": int(t), "window": 48 * 3600, "ev": evs}
    fb._flow_ev = fl(T8, [])
    web.alert_watch_once(wst, T8)
    conn_ok[0] = False
    web.alert_watch_once(wst, T8 + 60)
    off_ev = ev_out("off1", T8 + 120, "USDC", 40000, 40000.0)
    fb._flow_ev = fl(T8 + 100, [])
    conn_ok[0] = True
    a1 = web.alert_watch_once(wst, T8 + 300)
    fb._flow_ev = fl(T8 + 330, [off_ev])
    a2 = web.alert_watch_once(wst, T8 + 360)
    fb._flow_ev = fl(T8 + 400, [off_ev, ev_out("on1", T8 + 390, "ETH", 12, 30000.0)])
    a3 = web.alert_watch_once(wst, T8 + 420)
    check("R24 텔레그램 끊긴 동안의 출금 = 다시 연결해도 몰려오지 않음 · 그 뒤 새 출금은 1통",
          a1 == [] and a2 == [] and [x["kind"] for x in a3] == ["BIG_FLOW"] and "ETH" in a3[0]["text"] and "USDC" not in a3[0]["text"], (a1, a2, a3))
    fb.kicks = 0
    fb.sig, fb._built_sig = "a", "a"
    web._flow_fresh_kick(T8 + 1000)
    k0 = fb.kicks
    fb.sig = "b"
    web._flow_fresh_kick(T8 + 1000)
    check("R25 재빌드 요청 = 입력 서명이 바뀐 경우만(같으면 0번 · 바뀌면 1번)", k0 == 0 and fb.kicks == 1, (k0, fb.kicks))
    check("R43 (n5) 알림 감시 기억(alert_watch.json)은 빌드 입력 서명에서 뺌", "alert_watch.json" in web.StateBuilder._SIG_SKIP)
    wst = {}
    conn_ok[0] = True
    fb._flow_ev = fl(T11, [])
    web.alert_watch_once(wst, T11)
    conn_ok[0] = False
    web.alert_watch_once(wst, T11 + 60)
    conn_ok[0] = True
    fb._flow_ev = fl(T11 + 100, [])
    web.alert_watch_once(wst, T11 + 300)
    fb._flow_ev = fl(T11 + 330, [])
    b1 = web.alert_watch_once(wst, T11 + 360)
    fb._flow_ev = fl(T11 + 420, [ev_out("off44", T11 + 120, "USDC", 40000, 40000.0)])
    b2 = web.alert_watch_once(wst, T11 + 450)
    fb._flow_ev = fl(T11 + 520, [ev_out("off44", T11 + 120, "USDC", 40000, 40000.0), ev_out("on44", T11 + 500, "ETH", 12, 30000.0)])
    b3 = web.alert_watch_once(wst, T11 + 540)
    check("R44 재연결 뒤 빈 빌드 다음에 늦게 잡힌 끊긴 동안 출금 = 알림 없음 · 그 뒤 새 출금 1통", b1 == [] and b2 == []
          and [x["kind"] for x in b3] == ["BIG_FLOW"] and "ETH" in b3[0]["text"] and "USDC" not in b3[0]["text"], (b1, b2, b3))
else:
    check("R24·R25 web 가져오기", False)

T.finish()
