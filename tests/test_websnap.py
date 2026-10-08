#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import copy
import gzip
import hashlib
import json
import os
import random
import sqlite3
import stat
import time as _real_time
from datetime import datetime, timedelta, timezone

CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": [], "web": {"port": 1, "login": {"enabled": False}}}, f)
import common

assert T.TMP in common.STATE_DIR
import websnap as WS


class Clock:

    def __init__(self, t):
        self.t = float(t)

    def time(self):
        return self.t

    def __getattr__(self, name):
        return getattr(_real_time, name)


T0 = 1_900_000_000.0
CLK = Clock(T0)
WS.time = CLK


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


def J(o):
    return json.dumps(o, ensure_ascii=False)


def same(a, b):
    return J(a) == J(b)


def same_val(a, b):
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def gun(b):
    return json.loads(gzip.decompress(b))


def addr(i):
    return "0x" + ("%040x" % (0xABC000 + i))


def mkstate(rng, tick, n_pos=6, n_out=3):
    pos = []
    for i in range(n_pos):
        evs = [{"t": "%02d-%02d %02d:%02d" % (rng.randint(1, 12), rng.randint(1, 28), rng.randint(0, 23), rng.randint(0, 59)),
                "k": rng.choice(["buy", "sell"]), "q": rng.randint(1, 9)} for _ in range(rng.randint(0, 4))]
        pos.append({"key": f"P{i}", "sym": f"T{i}", "qty": rng.randint(0, 100) + tick, "events": evs})
    outs = []
    for i in range(n_out):
        r = {"address": addr(i), "usd": rng.randint(1, 999), "txs": [{"h": "0x%064x" % (tick * 100 + i * 10 + j)} for j in range(rng.randint(0, 3))],
             "flow": {"recips": [{"a": addr(100 + j), "txs": [{"h": "0x%064x" % (9999 + j)}]} if j % 2 == 0 else {"a": addr(200 + j)}
                                 for j in range(rng.randint(0, 3))]}}
        outs.append(r)
    return {"builtAt": 1000 + tick, "fields": {"lastScan": "30초 전 스캔", "rate": 1400.5, "positions": pos, "outflows": outs,
                                                "coins": [{"key": f"g{i}", "price": rng.choice([0, 1.5, 2]), "ok": rng.choice([True, 1])} for i in range(4)],
                                                "note": "한글 표시"}}


rng = random.Random(1008)
o1 = mkstate(rng, 1)
s1, s1b = WS.Snap(o1, 5), WS.Snap(copy.deepcopy(o1), 6)
check("S1a 버전 = 직렬화 바이트 sha1 앞 16자", s1.ver == hashlib.sha1(s1.raw).hexdigest()[:16] and len(s1.ver) == 16, s1.ver)
check("S1b 같은 내용 = 같은 버전 · 같은 gzip 바이트(mtime 0 — 결정적)", s1.ver == s1b.ver and s1.gz == s1b.gz)
check("S1c gzip 풀면 = 본문 · 본문 = json.dumps(ensure_ascii=False) 바이트(종전 _send 와 같음)",
      gzip.decompress(s1.gz) == s1.raw and s1.raw == json.dumps(o1, ensure_ascii=False).encode() and "한글 표시".encode() in s1.raw)
o1c = copy.deepcopy(o1)
o1c["fields"]["rate"] = 1400.6
check("S1d 값 하나 바뀌면 다른 버전", WS.Snap(o1c).ver != s1.ver)
check("S1e True ↔ 1 · 1 ↔ 1.0 도 다른 버전(파이썬 == 함정 없음)",
      WS.Snap({"a": True}).ver != WS.Snap({"a": 1}).ver and WS.Snap({"a": 1}).ver != WS.Snap({"a": 1.0}).ver)
check("S1f 세대·빌드 시각·시각(가짜 시계) 칸", s1.gen == 5 and s1.built_at == 1001 and s1.at == T0 and s1.hero is None and s1.slim_gz is None)
s1r = WS.Snap(None, 0, raw=b'{"x": 1}')
check("S1g raw 를 주면 그 바이트 그대로(다시 직렬화 안 함) · 객체 아님 = 빌드 시각 없음", s1r.raw == b'{"x": 1}' and s1r.built_at is None
      and s1r.ver == hashlib.sha1(b'{"x": 1}').hexdigest()[:16])
check("S1h 리스트 상태도 예외 없음", "_exc" not in T.safe(lambda: WS.Snap([1, 2]).ver))
check("S1i NaN 허용(종전 직렬화 allow_nan)", WS.dumps({"x": float("nan")}) == b'{"x": NaN}')

ODD = {"builtAt": 1, "fields": {
    "positions": [
        {"key": "A", "events": [{"t": "03-05 10:00"}, {"t": "03-20 09:00"}, {"t": "04-01 00:00"}, {"t": None}, "x"]},
        {"key": 7, "events": []},
        {"key": True, "events": [{"t": "01-01"}]},
        {"key": "B"},
        {"key": "C", "events": "깨짐"},
        "문자열 원소", None],
    "outflows": [
        {"address": addr(1), "txs": [1, 2, 3]},
        {"address": addr(2), "txs": "깨짐"},
        {"address": addr(3), "flow": {"recips": [{"a": 1, "txs": [9]}, {"a": 2}, "x", {"a": 3, "txs": []}]}},
        {"address": addr(4), "usd": 5},
        {"usd": 9, "txs": [1]},
        {"address": addr(5), "txs": [], "flow": "깨짐"},
        7],
    "other": {"k": [1, 2]}}}
cases = [ODD] + [mkstate(random.Random(s), s) for s in range(40)]
bad_rt, bad_mut, bad_strip = [], [], []
for i, ob in enumerate(cases):
    before = J(ob)
    slim, parts = WS.split_slim(ob)
    if J(ob) != before:
        bad_mut.append(i)
    back = WS.merge_slim(json.loads(J(slim)), json.loads(J(parts)))
    if not same_val(back, ob):
        bad_rt.append(i)
    for p in slim["fields"].get("positions") or []:
        if isinstance(p, dict) and isinstance(p.get("key"), (str, int)) and not isinstance(p.get("key"), bool) and "events" in p:
            bad_strip.append((i, "events", p.get("key")))
    for r in slim["fields"].get("outflows") or []:
        if isinstance(r, dict) and isinstance(r.get("address"), str):
            if "txs" in r:
                bad_strip.append((i, "txs", r["address"]))
            fl = r.get("flow")
            for x in (fl.get("recips") if isinstance(fl, dict) and isinstance(fl.get("recips"), list) else []):
                if isinstance(x, dict) and "txs" in x:
                    bad_strip.append((i, "rtxs", r["address"]))
check(f"S2a 되붙이기 = 원래 상태(값·키 존재 그대로) {len(cases)}건", not bad_rt, bad_rt)
check("S2b 나누기는 원본을 바꾸지 않음", not bad_mut, bad_mut)
_o9 = {"fields": {"outflows": [{"address": addr(9), "txs": None, "flow": {"recips": [{"a": 1, "txs": None}]}}]}}
_s9, _p9 = WS.split_slim(_o9)
print("SKIP S2x txs=null 칸 되붙이기(감수 — 빌드는 늘 리스트) · 지금 " + ("이제 통과" if same_val(WS.merge_slim(_s9, _p9), _o9) else "키 사라짐(종전 그대로)"))
check("S2c 가벼운 상태엔 사이클 기록·전송 목록이 없음", not bad_strip, bad_strip[:5])
slim, parts = WS.split_slim(ODD)
P = {p["key"]: p for p in slim["fields"]["positions"] if isinstance(p, dict) and "key" in p and not isinstance(p["key"], bool)}
check("S2d 요약 _evc(건수) · _evt(달마다 가장 늦은 시각 · 이상한 원소 = 빈 글자)",
      P["A"]["_evc"] == 5 and P["A"]["_evt"] == ["", "03-20 09:00", "04-01 00:00"] and P[7]["_evc"] == 0 and P["C"]["_evc"] == 0
      and "_evc" not in P["B"], (P["A"], P[7], P["C"], P["B"]))
check("S2e 불리언 키 위치는 그대로(조각으로 안 뺌)", any(isinstance(p, dict) and p.get("key") is True and "events" in p for p in slim["fields"]["positions"]))
O = {r["address"]: r for r in slim["fields"]["outflows"] if isinstance(r, dict) and "address" in r}
check("S2f 요약 _txn(건수 · 리스트 아님 = 0) · 상대마다 _rtn(상세 있던 상대만)",
      O[addr(1)]["_txn"] == 3 and O[addr(2)]["_txn"] == 0 and "_txn" not in O[addr(3)]
      and [x.get("_rtn") if isinstance(x, dict) else x for x in O[addr(3)]["flow"]["recips"]] == [1, None, "x", 0], O)
check("S2g 조각 표 = {'ev': {키: 기록}, 'oft': {주소: [전송, 상대별]}} · slim 표식",
      set(parts) == {"ev", "oft"} and parts["ev"]["7"] == [] and parts["oft"][addr(1)] == [[1, 2, 3], None]
      and parts["oft"][addr(3)][0] is None and parts["oft"][addr(3)][1] == [[9], None, None, []] and slim["slim"] == ["ev", "oft"], parts)
for junk in ([1, 2], None, {"fields": "깨짐"}, {"no": 1}):
    r9 = WS.split_slim(junk)
    check(f"S2h 상태 꼴이 아님({str(junk)[:16]}) = 그대로 · 빈 조각", r9[0] is junk and r9[1] == {"ev": {}, "oft": {}}, r9)
big = mkstate(random.Random(77), 77, n_pos=60, n_out=20)
for p in big["fields"]["positions"]:
    p["events"] = p["events"] * 10 + [{"t": "05-05 05:05", "memo": "x" * 200}]
sn = WS.attach_slim(WS.Snap(big), big)
sl9, pa9 = gun(sn.slim_gz), {n: gun(b) for n, b in sn.parts_gz.items()}
check("S2i attach_slim: gzip 가벼운 상태·조각 = split_slim 결과 바이트 · 되붙이면 전체 상태",
      gzip.decompress(sn.slim_gz) == WS.dumps(WS.split_slim(big)[0]) and set(pa9) == set(WS.PARTS) and same_val(WS.merge_slim(sl9, pa9), big))
check("S2j 가벼운 상태가 전체보다 작음(첫 화면 빠르게)", len(gzip.decompress(sn.slim_gz)) < len(sn.raw) / 2, (len(gzip.decompress(sn.slim_gz)), len(sn.raw)))


def mutate(rng, o):
    o = copy.deepcopy(o)
    f = o["fields"]
    for _ in range(rng.randint(1, 6)):
        r = rng.random()
        pos = f["positions"]
        if r < 0.2 and pos:
            pos[rng.randrange(len(pos))]["qty"] = rng.choice([0, 1, True, 1.0, None, "x", rng.randint(2, 99)])
        elif r < 0.3 and pos:
            pos.pop(rng.randrange(len(pos)))
        elif r < 0.4:
            pos.insert(rng.randint(0, len(pos)), {"key": "N%d" % rng.randint(0, 10 ** 6), "qty": 1, "events": []})
        elif r < 0.5:
            rng.shuffle(pos)
        elif r < 0.6:
            f["coins"] = [dict(c, price=rng.choice([0, 3])) for c in f["coins"]][::rng.choice([1, -1])]
        elif r < 0.7 and f["outflows"]:
            x = f["outflows"][rng.randrange(len(f["outflows"]))]
            x["usd"] = rng.randint(1, 10 ** 6)
            x.setdefault("txs", []).append({"h": "0x%064x" % rng.randint(0, 10 ** 9)})
        elif r < 0.75:
            f["new%d" % rng.randint(0, 3)] = {"z": rng.randint(0, 9)}
        elif r < 0.8:
            ks = [k for k in f if k not in ("positions", "outflows", "coins")]
            if ks:
                f.pop(rng.choice(ks), None)
        elif r < 0.85:
            o["fields"] = dict(reversed(list(f.items())))
            f = o["fields"]
        elif r < 0.9 and pos:
            pos.append(dict(pos[0]))
        else:
            f["lastScan"] = "%d초 전 스캔" % rng.randint(1, 80)
    return o


rd = random.Random(20261008)
bad_d, bad_mut = [], []
for i in range(300):
    a = mkstate(rd, i)
    b = mutate(rd, a)
    a0 = J(a)
    d = WS.diff(a, b)
    out = WS.apply(json.loads(a0), json.loads(J(d)))
    if not same(out, b):
        bad_d.append(i)
    if J(a) != a0:
        bad_mut.append(i)
check("S3a apply(a, diff(a, b)) = b(값·키 순서·True/1 구분까지) 무작위 300쌍", not bad_d, bad_d[:10])
check("S3b diff 는 입력을 바꾸지 않음", not bad_mut, bad_mut[:10])
a = mkstate(random.Random(5), 5)
check("S3c 같은 상태 = 빈 패치", WS.diff(a, copy.deepcopy(a)) == {})
check("S3d True → 1 은 바뀜으로 잡음", WS.diff({"x": True}, {"x": 1}) == {"$s": {"x": 1}} and WS.diff({"x": 1}, {"x": 1.0}) == {"$s": {"x": 1.0}})
check("S3e 키 순서만 다름 = $o 만", WS.diff({"a": 1, "b": 2}, {"b": 2, "a": 1}) == {"$o": ["b", "a"]})
MEMO = "m" * 300
la = [{"address": addr(1), "v": 1, "memo": MEMO}, {"address": addr(2), "v": 2, "memo": MEMO}]
lb = [{"address": addr(2), "v": 3, "memo": MEMO}, {"address": addr(3), "v": 4}]
dl = WS.diff({"o": la}, {"o": lb})
pl = dl.get("$p", {}).get("o") or {}
check("S3f 주소 키 리스트(보낸 내역) = keyed 패치(k=address · 새 원소·지움·하위 패치)",
      pl.get("$L") == 1 and pl.get("k") == "address" and pl.get("r") == [addr(1)] and [e["address"] for e in pl.get("n") or []] == [addr(3)]
      and same(WS.apply({"o": la}, dl), {"o": lb}), dl)
dup = [{"key": 1}, {"key": 1}]
check("S3g 키 중복·불리언 키 리스트 = keyed 아님(통째 $s)", WS.diff({"l": dup}, {"l": dup + [{"key": 2}]}) == {"$s": {"l": dup + [{"key": 2}]}}
      and "$s" in WS.diff({"l": [{"key": True}]}, {"l": [{"key": True}, {"key": 2}]}))
big_a = {"rows": [{"key": f"k{i}", "v": "x" * 50, "n": i} for i in range(300)]}
big_b = copy.deepcopy(big_a)
big_b["rows"][150]["n"] = -1
dd = WS.diff(big_a, big_b)
check("S3h 큰 리스트의 칸 하나 = 작은 패치(통째보다 훨씬 작음)", len(J(dd)) < 120 and same(WS.apply(big_a, dd), big_b), J(dd)[:200])
check("S3i 패치가 통째 값보다 크면 통째 값($s)", WS.diff({"x": {"a": 1}}, {"x": {"b": 2}}) == {"$s": {"x": {"b": 2}}})
check("S3j 빈 리스트 → 리스트 = 통째", WS.diff({"l": []}, {"l": [{"key": 1}]}) == {"$s": {"l": [{"key": 1}]}})


def snap_at(obj, t, gen=0):
    CLK.t = t
    return WS.Snap(obj, gen)


def st_obj(i):
    return {"builtAt": i, "fields": {"lastScan": "1초 전 스캔", "n": i, "rows": [{"key": f"r{j}", "v": (i if j == 3 else j)} for j in range(40)]}}


st = WS.SnapStore()
CLK.t = T0
check("S4a 빈 링 = 델타 없음", st.delta_gz("x") is None and st.part_gz("x", "ev") is None)
a0 = snap_at(st_obj(0), T0)
st.publish(a0)
check("S4b 지금 버전을 since 로 = 빈 응답(b'') · 모르는 버전 = None(전체를 보내라)", st.delta_gz(a0.ver) == b"" and st.delta_gz("0" * 16) is None)
a1 = snap_at(st_obj(1), T0 + 60)
st.publish(a1)
dg = st.delta_gz(a0.ver)
body = gun(dg) if dg else {}
check("S4c 옛 버전 → 델타(v=지금 · b=옛 · d 적용 = 지금 상태)", body.get("v") == a1.ver and body.get("b") == a0.ver
      and same(WS.apply(st_obj(0), body.get("d") or {}), st_obj(1)), body)
check("S4d 같은 요청 두 번째 = 메모(같은 바이트 객체)", st.delta_gz(a0.ver) is dg)
check("S4e 대상 스냅숏이 지금과 다르면 None(받은 버전과 다른 답 안 함)", st.delta_gz(a0.ver, target=a0) is None and st.delta_gz(a0.ver, target=a1) is dg)
st2 = WS.SnapStore()
st2.publish(snap_at(st_obj(0), T0))
st2.publish(snap_at(st_obj(1), T0 + 1))
check("S4f compute=False · 메모 없음 = None(요청 경로는 계산 안 함)", st2.delta_gz(a0.ver, compute=False) is None)
a1b = snap_at(st_obj(1), T0 + 90, gen=9)
st.publish(a1b)
check("S4g 같은 내용 다시 게시 = 링 무변 · 지금 스냅숏(세대)만 교체", st.cur is a1b and st.order == [a0.ver] and st.delta_gz(a0.ver) is dg)
st3 = WS.SnapStore()
st3.publish(snap_at({"a": "x" * 10}, T0))
st3.publish(snap_at({"b": [1]}, T0 + 1))
v_small = WS.Snap({"a": "x" * 10}).ver
check("S4h 델타가 전체보다 크면 None(= 전체) · 그 판정도 메모", st3.delta_gz(v_small) is None and st3.memo.get((v_small, st3.cur.ver), "없음") is None)

ring = WS.SnapStore()
vers = []
for i in range(120):
    s9 = snap_at(st_obj(1000 + i), T0 + i * 60)
    vers.append(s9.ver)
    ring.publish(s9)
kept = list(ring.order)
check("S4i 최근 16개(지금 제외)는 늘 남음", kept[-16:] == vers[-17:-1], (len(kept), kept[-3:], vers[-4:-1]))
anc = [v for v in kept if v not in vers[-17:-1]]
ats = [ring.old[v][0] for v in anc]
check("S4j 그 밖은 30분 간격 앵커만(2시간 → 3~4개)", 2 <= len(anc) <= 5 and all(b - a >= 1800 for a, b in zip(ats, ats[1:])), (len(anc), ats))
gone = [v for v in vers[:-17] if v not in ring.old]
check("S4k 링 밖 버전 = 델타 없음(전체 · 가벼운 상태 경로)", len(gone) >= 90 and all(ring.delta_gz(v, compute=True) is None for v in gone[:20]), len(gone))
CLK.t = T0 + 120 * 60 + 86400 + 10
ring.publish(snap_at(st_obj(5000), CLK.t))
check("S4l 24시간 넘은 앵커는 버림(최근 16개는 시각과 무관하게 남음)", all(ring.old[v][0] >= CLK.t - 86400 or v in ring.order[-16:]
                                                                    for v in ring.order) and len(ring.order) == 16, len(ring.order))

pin = WS.SnapStore()
p0 = snap_at(st_obj(0), T0)
pin.publish(p0)
pin.pin(p0.ver, now=T0)
for i in range(1, 60):
    pin.publish(snap_at(st_obj(i), T0 + i * 60))
check("S4m 붙잡은 버전 = 링에서 밀려도 남고 델타 = 지금 상태", p0.ver in pin.old and same(WS.apply(st_obj(0), gun(pin.delta_gz(p0.ver))["d"]), st_obj(59)))
pin2 = WS.SnapStore()
pv = []
for i in range(40):
    s9 = snap_at(st_obj(i), T0 + i * 60)
    pv.append(s9.ver)
    pin2.publish(s9)
    if i < 8:
        pin2.pin(s9.ver, now=T0 + i * 60)
check("S4n 붙잡기 최대 6개(최근에 내민 순) · 나머지는 풀림 · 붙잡은 버전은 링에 남음", set(pin2.pins) == set(pv[2:8]) and all(v in pin2.old for v in pv[2:8])
      and pv[1] not in pin2.old, (len(pin2.pins),))
pin2.hold(pv[2], now=T0 + 3000)
pin2.hold(pv[20], now=T0 + 3000)
check("S4o hold = 붙잡은 버전만 시각 연장 · 안 붙잡은 버전은 무시", pin2.pins[pv[2]] == T0 + 3000 and pv[20] not in pin2.pins)
CLK.t = T0 + 2400 + 86400 + 1
pin2.publish(snap_at(st_obj(999), CLK.t))
check("S4p 하루(PIN_SEC) 지난 붙잡기는 풀림 · 그 안에 hold 로 연장한 것만 남음", set(pin2.pins) == {pv[2]}, sorted(pin2.pins))
pin2.pin("", now=T0)
pin2.hold(None)
check("S4q 빈 버전 붙잡기·hold = 무시", "" not in pin2.pins and None not in pin2.pins)

pt = WS.SnapStore()
pvs = []
for i in range(30):
    o9 = mkstate(random.Random(i), i)
    s9 = WS.attach_slim(snap_at(o9, T0 + i * 60), o9)
    pvs.append((s9.ver, s9.parts_gz))
    pt.publish(s9)
check("S4r 지금 버전 조각", pt.part_gz(pvs[-1][0], "ev") == pvs[-1][1]["ev"] and pt.part_gz(pvs[-1][0], "zz") is None)
check("S4s 직전 버전 조각도 남음(10분 안 · 최대 16)", pt.part_gz(pvs[-2][0], "oft") == pvs[-2][1]["oft"] and 4 <= len(pt.parts_old) <= 16, len(pt.parts_old))
CLK.t = T0 + 30 * 60 + 600 + 1
pt.publish(WS.attach_slim(snap_at(st_obj(77), CLK.t), st_obj(77)))
check("S4t 10분 지나면 직전 4개만", len(pt.parts_old) == 4 and pt.part_gz(pvs[-1][0], "ev") == pvs[-1][1]["ev"]
      and pt.part_gz(pvs[0][0], "ev") is None, len(pt.parts_old))

pc = WS.SnapStore()
q0 = snap_at(st_obj(0), T0)
pc.publish(q0)
q1 = snap_at(st_obj(1), T0 + 10)
pc.publish(q1)
CLK.t = T0 + 20
pc.note_served(q0.ver)
pc.note_served(q1.ver)
q2 = snap_at(st_obj(2), T0 + 100)
pc.publish(q2)
CLK.t = T0 + 130
pc.wanted[q1.ver] = T0 + 0
pc.precompute()
check("S4u 선계산 = 2분 안 버전만 메모 · 오래된 요청 기록은 지움", (q0.ver, q2.ver) in pc.memo and (q1.ver, q2.ver) not in pc.memo and q1.ver not in pc.wanted,
      (list(pc.memo), list(pc.wanted)))

os.makedirs(common.STATE_DIR, exist_ok=True)
con = sqlite3.connect(common.DB_PATH)
con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
con.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", "2"), ("ext_rebuilt_at", "100")])
con.commit()
con.close()
try:
    import web
except Exception as e9:
    web = None
    check("S5 web 가져오기", False, e9)
if web is not None:
    KST = timezone(timedelta(hours=9))
    DAY = [datetime(2030, 3, 14, 12, 0, tzinfo=KST)]

    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return DAY[0] if tz is not None else DAY[0].replace(tzinfo=None)

    web.time = CLK
    web.datetime = FixedDT
    web.SNAPFILE_PATH = os.path.join(common.STATE_DIR, "web_snap_last.bin")
    SP = web.SNAPFILE_PATH
    T5 = T0 + 10 ** 6
    ob = mkstate(random.Random(55), 55)
    CLK.t = T5
    sn = WS.attach_slim(WS.Snap(ob, 4), ob)
    sn.hero = {"todayKey": "03-14", "total": "합성"}

    def load(elapsed, gen=11):
        CLK.t = T5 + elapsed
        return web._snapfile_load(gen, 10 ** 9)

    ok9 = web._snapfile_save(sn, force=True)
    mode = stat.S_IMODE(os.stat(SP).st_mode) if os.path.exists(SP) else None
    check("S5a 저장 = 파일 0600 · 임시 파일 안 남김", ok9 is True and mode == 0o600 and not os.path.exists(SP + ".tmp"), (ok9, oct(mode or 0)))
    with open(SP, "rb") as f:
        disk = f.read()
    check("S5b 저장본 머리 = 매직 · 버전", disk.startswith(b"TJSNAP1\n") and sn.ver.encode() in disk[:600], disk[:80])
    r0 = load(0)
    check("S5c 바로 복원 = 같은 버전·본문·gzip·가벼운 상태·조각 바이트 · 세대 = 기동 세대 · hero",
          r0 is not None and r0.ver == sn.ver and r0.raw == sn.raw and r0.gz == sn.gz and r0.slim_gz == sn.slim_gz
          and r0.parts_gz == sn.parts_gz and r0.gen == 11 and r0.hero == sn.hero and r0.built_at == sn.built_at and r0.at == sn.at,
          None if r0 is None else (r0.ver, sn.ver, r0.gen))
    r1 = load(120)
    j1 = json.loads(r1.raw) if r1 is not None else {}
    sl1 = gun(r1.slim_gz) if r1 is not None else {}
    ob2 = copy.deepcopy(ob)
    ob2["fields"]["lastScan"] = "2분 전 스캔"
    check("S5d 2분 뒤 복원 = 수집 나이만 늘림(30초 → 2분 · 본문·가벼운 상태 둘 다) · 새 버전 키 = 새 본문 해시",
          r1 is not None and same(j1, ob2) and sl1["fields"]["lastScan"] == "2분 전 스캔" and r1.ver == hashlib.sha1(r1.raw).hexdigest()[:16]
          and r1.ver != sn.ver and gzip.decompress(r1.gz) == r1.raw, (j1.get("fields", {}).get("lastScan"), sl1.get("fields", {}).get("lastScan")))
    check("S5e 30분(SNAPFILE_MAX_AGE) 정확히 = 씀 · 1초 넘음 = 안 씀(파일은 둠)", load(1800 + 1) is None and os.path.exists(SP) and load(1800) is not None)
    check("S5f 시각이 미래(1분 넘게) = 안 씀", load(-120) is None)
    DAY[0] = datetime(2030, 3, 15, 0, 1, tzinfo=KST)
    check("S5g 날짜 바뀜(hero.todayKey) = 안 씀", load(0) is None)
    DAY[0] = datetime(2030, 3, 14, 12, 0, tzinfo=KST)
    c9 = sqlite3.connect(common.DB_PATH)
    c9.execute("UPDATE meta SET v='200' WHERE k='ext_rebuilt_at'")
    c9.commit()
    c9.close()
    check("S5h 원장 세대(ext_rebuilt_at) 바뀜 = 안 씀", load(0) is None)
    c9 = sqlite3.connect(common.DB_PATH)
    c9.execute("UPDATE meta SET v='100' WHERE k='ext_rebuilt_at'")
    c9.commit()
    c9.close()
    check("S5i 원장 세대 되돌리면 다시 씀", load(0) is not None)
    with open(CP, "w", encoding="utf-8") as f:
        json.dump({"chains": {}, "wallets": [], "web": {"port": 2, "login": {"enabled": False}}}, f)
    check("S5j 실행 중 config.json 이 바뀌어도 서명 = 기동 때 읽은 설정(재시작 전 빌드 그대로 씀)", load(0) is not None)
    web._SIG0.clear()
    check("S5k 새 설정으로 재시작 = 안 씀(설정 서명 다름)", load(0) is None)
    web._SIG0.clear()
    CLK.t = T5
    web._snapfile_save(sn, force=True)
    CLK.t = T5 + 299
    check("S5l 같은 버전은 다시 안 씀 · 5분(SNAPFILE_EVERY) 안 새 버전도 안 씀",
          web._snapfile_save(sn) is False and web._snapfile_save(WS.Snap({"fields": {"lastScan": "1초 전 스캔"}})) is False)
    CLK.t = T5 + 300 + 1
    sn2 = WS.Snap({"fields": {"lastScan": "1초 전 스캔"}, "x": 1})
    sn2.hero = {"todayKey": "03-14"}
    check("S5m 쓰는 사이 무효화(still_ok 거짓) = 방금 쓴 것도 지움", web._snapfile_save(sn2, still_ok=lambda: False) is False and not os.path.exists(SP))
    CLK.t = T5
    web._snapfile_save(sn, force=True)
    with open(SP, "rb") as f:
        raw9 = bytearray(f.read())
    raw9[-5] ^= 0xFF
    with open(SP, "wb") as f:
        f.write(bytes(raw9))
    check("S5n 깨진 저장본(바이트 해시 불일치) = 안 씀 · 지움", load(0) is None and not os.path.exists(SP))
    with open(SP, "wb") as f:
        f.write(b"NOTSNAP\n...")
    check("S5o 매직 아님 = 안 씀 · 지움", load(0) is None and not os.path.exists(SP))
    sn3 = WS.Snap({"fields": {"n": 1}})
    sn3.hero = {"todayKey": "03-14"}
    CLK.t = T5
    web._snapfile_save(sn3, force=True)
    check("S5p 수집 시각 칸 없는 본문 = 안 씀", load(0) is None)
    sn4 = WS.Snap({"fields": {"lastScan": "10초 전 스캔", "n": 4}})
    sn4.hero = {"todayKey": "03-14"}
    CLK.t = T5
    web._snapfile_save(sn4, force=True)
    r4 = load(0)
    check("S5q 가벼운 상태 없는 스냅숏도 왕복(가벼운 상태·조각 = 없음)", r4 is not None and r4.raw == sn4.raw and r4.slim_gz is None and r4.parts_gz is None,
          None if r4 is None else (r4.slim_gz, r4.parts_gz))
    A = web._aged_last_scan
    check("S5r 수집 나이: 30초+50초 = 80초 · 30초+70초 = 1분 · 5분+0 = 5분",
          A('{"lastScan": "30초 전 스캔"}'.encode(), 50) == '{"lastScan": "80초 전 스캔"}'.encode()
          and A('{"lastScan": "30초 전 스캔"}'.encode(), 70) == '{"lastScan": "1분 전 스캔"}'.encode()
          and A('{"lastScan": "5분 전 스캔"}'.encode(), 0) == '{"lastScan": "5분 전 스캔"}'.encode())
    check("S5s 나이 없는 글자('수집 대기') = 그대로 · 칸 없음·두 번·따옴표 없는 값 = None(안 씀)",
          A('{"lastScan": "수집 대기"}'.encode(), 99) == '{"lastScan": "수집 대기"}'.encode() and A(b'{"x": 1}', 1) is None
          and A(b'{"lastScan": "a", "y": {"lastScan": "b"}}', 1) is None and A(b'{"lastScan": 5}', 1) is None
          and A(b'{"lastScan": "a\\"b"}', 1) is None)

T.finish()
