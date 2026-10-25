#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
SD = os.path.join(T.TMP, "pxs")
os.makedirs(SD, exist_ok=True)
TOOL = os.path.join(T.ROOT, "tools", "px_flip_fix.py")
D = ["2026-09-%02d" % d for d in range(10, 20)]
LIVE, GT = 2.5e-06, 0.02
GT_DAYS = D[1:4]
FF_DAYS = D[4:7]
dcs = {"_v": 1, "s": {"ca:eth:0xj": {"st": "ok", "lo": "2026-08-01", "hi": "2026-09-20", "src": ["geckoterminal"], "at": 1,
                                     "p": {d: GT for d in GT_DAYS}},
                      "ca:eth:0xs": {"st": "ok", "lo": "2026-08-01", "hi": D[-1], "src": ["coingecko"], "at": 1, "p": {d: 7.0 for d in D}}}}
hp = {"_v": 1, "specs": {}}
dpx, dcache = {"_v": 1, "_pxfix": {"v": 1}}, {"_v": 1, "_risk_rev": "99"}
for d in D:
    jd = d in GT_DAYS or d in FF_DAYS
    blk = {"p": {"7": GT if jd else LIVE, "8": 7.0, "99": GT if jd else LIVE}, "k": {"7": "d", "8": "d", "99": "d"} if jd else {"8": "d"},
           "fp": {"7": LIVE, "8": 1.0, "99": LIVE} if jd else {"8": 1.0}}
    if not jd:
        blk["k"]["7"] = "live"
    dpx[d] = dict(json.loads(json.dumps(blk)), x=1.0, xk="calc")
    g = {"7": round(100000 * blk["p"]["7"], 4), "8": 70.0, "99": round(50000 * blk["p"]["99"], 4)}
    dcache[d] = {"val": round(1000 + g["7"] + g["8"], 2), "g": g, "est": 0.0, "src": "calc", "px": blk, "dcp": {"7": GT} if jd else {}}
dpx["2026-09-20"] = {"p": {"7": GT}, "k": {"7": "d"}, "fp": {"7": LIVE}}
dcs["s"]["ca:base:0xj"] = json.loads(json.dumps(dcs["s"]["ca:eth:0xj"]))
for name, obj in (("daily_close_px.json", dcs), ("curve_hist_px.json", hp), ("daily_px.json", dpx), ("daily_cache.json", dcache)):
    with open(os.path.join(SD, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
GROUPS = {7: [("token", "eth", "0xj", "TKJ")], 8: [("token", "eth", "0xs", "TKS")], 99: [("token", "base", "0xj", "TKQ")]}


def mkledger(sd, groups=None):
    c = sqlite3.connect(os.path.join(sd, "ledger.db"))
    c.execute("CREATE TABLE asset_groups (group_id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    c.execute("CREATE TABLE assets (asset_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, chain TEXT, address TEXT, symbol TEXT, group_id INTEGER)")
    for gid, rows in (GROUPS if groups is None else groups).items():
        c.execute("INSERT INTO asset_groups VALUES (?, ?)", (gid, rows[0][3] + "#" + str(gid)))
        c.executemany("INSERT INTO assets (kind, chain, address, symbol, group_id) VALUES (?, ?, ?, ?, ?)", [r + (gid,) for r in rows])
    c.commit()
    c.close()


mkledger(SD)


def h(name):
    with open(os.path.join(SD, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
    env.update(TJ_BASE=T.TMP, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, TOOL, "--state", SD, *args], env=env, capture_output=True, text=True, timeout=120)


H0 = {n: h(n) for n in ("daily_px.json", "daily_cache.json", "daily_close_px.json")}
r = run("--json")
try:
    o = json.loads(r.stdout)
except ValueError:
    o = {}
chk(r.returncode == 0 and o.get("cells") == 13 and set(o.get("groups") or {}) == {"7", "99"} and o["groups"]["7"]["days"] == 7
    and o["groups"]["7"]["usd_digits"] == "10^3" and o["groups"]["7"]["src"] == ["ca:eth:0xj"] and o["groups"]["99"]["src"] == ["ca:base:0xj"]
    and o.get("noid") == 0 and not o.get("applied"), "X1 점검 = 그룹 7(7일 · 하루 최대 10^3) · 격리 99 · 근거 강한 8 제외 · 출처 키 = 그 그룹 코인", (o, r.stderr[-400:]))
chk({n: h(n) for n in H0} == H0, "X1 점검 = 파일 무변")
UNDO = os.path.join(T.TMP, "undo_px.json")
r = run("--apply", "--undo-out", UNDO)
dpx2 = json.load(open(os.path.join(SD, "daily_px.json"), encoding="utf-8"))
dc2 = json.load(open(os.path.join(SD, "daily_cache.json"), encoding="utf-8"))
fixed = GT_DAYS + FF_DAYS
chk(r.returncode == 0 and all(dpx2[d]["p"]["7"] == LIVE and "7" not in dpx2[d]["k"] and "7" in dpx2[d]["dcn"] and "7" not in dpx2[d]["fp"] for d in fixed)
    and dpx2["2026-09-20"]["p"]["7"] == LIVE, "X2 그룹 7 = 기준가(근사) · 종류 지움 · 근사 확정 · 교정 전 가격 지움(daily_px 만 있는 날 포함)", (r.stdout, r.stderr[-400:]))
chk(all(dc2[d]["px"] == {k: dpx2[d][k] for k in dc2[d]["px"]} and set(dc2[d]["px"]) <= set(dpx2[d]) for d in fixed), "X2 가격 블록 = daily_px 그날 가격 칸")
chk(all(abs(dc2[d]["g"]["7"] - 100000 * LIVE) < 1e-6 and abs(dc2[d]["val"] - (1000 + 0.25 + 70)) < 0.011 and "7" not in dc2[d]["dcp"] for d in fixed),
    "X2 동결 항목 g · val = 근사가로 · 완료 표식 지움", [(dc2[d]["g"]["7"], dc2[d]["val"]) for d in fixed])
chk(all(dpx2[d]["k"]["8"] == "d" and dpx2[d]["p"]["8"] == 7.0 for d in D) and all(dc2[d]["val"] == dcache[d]["val"] for d in D if d not in fixed),
    "X2 근거 강한 출처(코인게코 봉 · 같은 값) · 안 고친 날 = 그대로")
chk(all(abs(dc2[d]["g"]["99"] - 50000 * LIVE) < 1e-6 for d in fixed), "X2 격리 그룹 = g 만(val 무변 — 위 val 식에 없음)")
chk(h("daily_close_px.json") == H0["daily_close_px.json"] and dpx2[D[0]].get("x") == 1.0, "X2 저장본(그날 마감가) · 그날 다른 칸(x) 무변")
r2 = run("--json")
chk(json.loads(r2.stdout or "{}").get("cells") == 0, "X2 다시 점검 = 고칠 칸 0(멱등)", r2.stdout[-300:])
r = run("--undo", UNDO)
chk(r.returncode == 0 and {n: h(n) for n in H0} != H0 and json.load(open(os.path.join(SD, "daily_px.json"), encoding="utf-8")) == dpx
    and json.load(open(os.path.join(SD, "daily_cache.json"), encoding="utf-8")) == dcache, "X3 되돌림 = 원래 내용 그대로", (r.stdout, r.stderr[-300:]))
UNDO_B = os.path.join(T.TMP, "undo_px_b.json")
r = run("--apply", "--undo-out", UNDO_B)
dpx3 = json.load(open(os.path.join(SD, "daily_px.json"), encoding="utf-8"))
dpx3[D[2]]["p"]["8"] = 7.5
with open(os.path.join(SD, "daily_px.json"), "w", encoding="utf-8") as f:
    json.dump(dpx3, f)
r = run("--undo", UNDO_B)
dpx4 = json.load(open(os.path.join(SD, "daily_px.json"), encoding="utf-8"))
chk(r.returncode == 2 and dpx4[D[2]]["p"]["8"] == 7.5 and dpx4[D[3]]["p"]["7"] == GT, "X3 그 뒤 바뀐 날 = 건너뜀(나머지만 되돌림)", r.stdout[-300:])
SD2 = os.path.join(T.TMP, "pxs2")
os.makedirs(SD2, exist_ok=True)
DL = D[2]
legacy_dpx = {"_v": 1, DL: {"p": {"7": GT}, "k": {"7": "d"}, "fp": {"7": LIVE}}}
legacy_dc = {"_v": 1, "_risk_rev": "", DL: {"val": 1000.25, "g": {"7": 100000 * LIVE}, "src": "calc"}}
for name, obj in (("daily_close_px.json", dcs), ("curve_hist_px.json", hp), ("daily_px.json", legacy_dpx), ("daily_cache.json", legacy_dc)):
    with open(os.path.join(SD2, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
mkledger(SD2)
env2 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
env2.update(TJ_BASE=T.TMP, PYTHONDONTWRITEBYTECODE="1")
r = subprocess.run([sys.executable, TOOL, "--state", SD2, "--apply", "--undo-out", os.path.join(T.TMP, "undo2.json")], env=env2, capture_output=True, text=True, timeout=120)
l_dc = json.load(open(os.path.join(SD2, "daily_cache.json"), encoding="utf-8"))
l_px = json.load(open(os.path.join(SD2, "daily_px.json"), encoding="utf-8"))
chk(r.returncode == 0 and l_dc[DL]["val"] == 1000.25 and abs(l_dc[DL]["g"]["7"] - 100000 * LIVE) < 1e-9 and l_px[DL]["p"]["7"] == LIVE and "px" not in l_dc[DL],
    "X4 옛 형식 항목(교정 흔적만 daily_px) = g·val 그대로 · 고정가만 근사로(다시 축소 안 함)", (r.stdout, r.stderr[-300:], l_dc[DL]))
SD5 = os.path.join(T.TMP, "pxs5")
os.makedirs(SD5, exist_ok=True)
for name, obj in (("daily_close_px.json", dcs), ("curve_hist_px.json", hp), ("daily_px.json", dpx), ("daily_cache.json", dcache)):
    with open(os.path.join(SD5, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
VICTIM = os.path.join(SD5, "ledger.db")
with open(VICTIM, "wb") as f:
    f.write(b"SQLite format 3\x00TKJ")
r5 = subprocess.run([sys.executable, TOOL, "--state", SD5, "--apply", "--undo-out", VICTIM], env=env2, capture_output=True, text=True, timeout=120)
with open(VICTIM, "rb") as f:
    vb = f.read()
chk(r5.returncode != 0 and vb == b"SQLite format 3\x00TKJ" and json.load(open(os.path.join(SD5, "daily_px.json"), encoding="utf-8")) == dpx,
    "X5 --undo-out 이 이미 있는 파일 = 거부 · 그 파일·state 무변", (r5.returncode, r5.stdout[-200:], r5.stderr[-300:]))
BAD = os.path.join(T.TMP, "undo_bad.json")
with open(BAD, "w", encoding="utf-8") as f:
    json.dump({"v": 1, "at": 1, "days": {"_v": {"dpx": 2, "dc": 5, "dpx_h": hashlib.sha256(json.dumps(1, sort_keys=True).encode()).hexdigest(), "dc_h": ""},
                                          D[0]: {"dpx": None, "dc": None, "dpx_h": "", "dc_h": ""}}}, f)
H5 = {n: hashlib.sha256(open(os.path.join(SD5, n), "rb").read()).hexdigest() for n in ("daily_px.json", "daily_cache.json")}
r5 = subprocess.run([sys.executable, TOOL, "--state", SD5, "--undo", BAD, "--force"], env=env2, capture_output=True, text=True, timeout=120)
chk(r5.returncode != 0 and {n: hashlib.sha256(open(os.path.join(SD5, n), "rb").read()).hexdigest() for n in H5} == H5,
    "X5 되돌리기 파일 날 키가 날짜 아님(_v) = 전체 거부 · 쓰기 0(--force 여도)", (r5.returncode, r5.stdout[-200:], r5.stderr[-300:]))
SD6 = os.path.join(T.TMP, "pxs6")
os.makedirs(SD6, exist_ok=True)
dcs6 = json.loads(json.dumps(dcs))
dcs6["s"]["ca:eth:0xo"] = {"st": "ok", "lo": D[1], "hi": D[1], "src": ["geckoterminal"], "at": 1, "p": {D[1]: GT}}
hp6 = {"_v": 1, "specs": {"ca:eth:0xj": json.loads(json.dumps(dcs["s"]["ca:eth:0xj"]))}}
for name, obj in (("daily_close_px.json", dcs6), ("curve_hist_px.json", hp6), ("daily_px.json", dpx), ("daily_cache.json", dcache)):
    with open(os.path.join(SD6, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
mkledger(SD6, {**GROUPS, 7: [("token", "eth", "0xj", "TKJ"), ("token", "arbitrum", "0xj2", "TKJ")]})


def run6(*args):
    r9 = subprocess.run([sys.executable, TOOL, "--state", SD6, "--json", *args], env=env2, capture_output=True, text=True, timeout=120)
    try:
        return r9, json.loads(r9.stdout)
    except ValueError:
        return r9, {}


r6, o6 = run6()
chk(r6.returncode == 0 and o6.get("cells") == 13 and (o6.get("groups") or {}).get("7", {}).get("days") == 7,
    "X6 다른 코인(그룹 정체 밖 키)의 같은 날 같은 값 = 근거로 안 봄(그 그룹 출처로만 판단 · 13칸 그대로) · 같은 키가 두 저장본에 있으면 한 출처(종전)", (o6, r6.stderr[-300:]))
dcs6["s"]["ca:arbitrum:0xj2"] = {"st": "ok", "lo": D[1], "hi": D[1], "src": ["geckoterminal"], "at": 1, "p": {D[1]: GT}}
with open(os.path.join(SD6, "daily_close_px.json"), "w", encoding="utf-8") as f:
    json.dump(dcs6, f)
r6, o6 = run6()
chk(r6.returncode == 0 and o6.get("cells") == 12 and (o6.get("groups") or {}).get("7", {}).get("days") == 6,
    "X6 그 그룹 자기 출처 키 둘이 같은 날 같은 값 = 어느 키인지 모름 → 그 날만 안 고침(종전 규칙 · 13→12칸)", (o6, r6.stderr[-300:]))

DX = "2026-08-10"
PX7 = {"p": {"7": 4.0, "8": 10}, "k": {"7": "d"}, "fp": {"7": 1.0}, "lp": {"7": 1.0}}
DP7 = {DX: json.loads(json.dumps(PX7)), "2026-08-11": {"p": {"8": 10}, "tkj": "same"}}
DC7 = {DX: {"val": 4010, "est": 0, "g": {"7": 4000, "8": 10}, "dcp": {"7": 1}, "px": json.loads(json.dumps(PX7))}, "2026-08-11": {"val": 10, "tkj": "same"}}
ENT7 = {"lo": DX, "hi": DX, "p": {DX: 4.0}, "st": "ok", "src": ["geckoterminal"]}
OTHER = "ca:base:0x" + "cd" * 20
for name7, ents, grp, want_cells, want_noid in (("다른 코인 한 키", {OTHER: ENT7}, GROUPS, 0, 0),
                                                ("다른 코인 두 키", {OTHER: ENT7, OTHER[:-2] + "ef": ENT7}, GROUPS, 0, 0),
                                                ("대상 코인 자기 키(대조)", {"ca:eth:0xj": ENT7, OTHER: ENT7}, GROUPS, 1, 0),
                                                ("하이퍼리퀴드 정식표 코인(UBTC → sym:BTC)", {"sym:BTC": ENT7}, {**GROUPS, 7: [("exchange_currency", None, "hyperliquid:UBTC", "UBTC")]}, 1, 0),
                                                ("거래소 비대표 코인 + 같은 심볼 시세 키만(sym:TKJ)", {"sym:TKJ": ENT7}, {**GROUPS, 7: [("exchange_currency", None, "bithumb:TKJ", "TKJ")]}, 0, 0),
                                                ("거래소 대표 코인(BTC) = 심볼 시세 키", {"sym:BTC": ENT7}, {**GROUPS, 7: [("exchange_currency", None, "bithumb:BTC", "BTC")]}, 1, 0),
                                                ("하이퍼리퀴드 고유 '이름@번호'", {"ex:hyperliquid:TKJ@12": ENT7}, {**GROUPS, 7: [("exchange_currency", None, "hyperliquid:TKJ@12", "TKJ@12")]}, 1, 0),
                                                ("원장에 그룹 없음", {"ca:eth:0xj": ENT7}, {8: GROUPS[8]}, 0, 1),
                                                ("원장 없음", {"ca:eth:0xj": ENT7}, None, 0, 1)):
    sd7 = os.path.join(T.TMP, "px7_" + str(abs(hash(name7)) % 10 ** 8))
    os.makedirs(sd7, exist_ok=True)
    for name, obj in (("daily_close_px.json", {"_v": 1, "s": ents}), ("curve_hist_px.json", {"_v": 1, "specs": {}}), ("daily_px.json", DP7), ("daily_cache.json", DC7)):
        with open(os.path.join(sd7, name), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    if grp is not None:
        mkledger(sd7, grp)
    u7 = os.path.join(sd7, "undo7.json")
    ra = subprocess.run([sys.executable, TOOL, "--state", sd7, "--json"], env=env2, capture_output=True, text=True, timeout=120)
    rb = subprocess.run([sys.executable, TOOL, "--state", sd7, "--json", "--apply", "--undo-out", u7], env=env2, capture_output=True, text=True, timeout=120)
    try:
        oa, ob = json.loads(ra.stdout), json.loads(rb.stdout)
    except ValueError:
        oa, ob = {}, {}
    dc7 = json.load(open(os.path.join(sd7, "daily_cache.json"), encoding="utf-8"))
    if want_cells == 0:
        chk(ra.returncode == rb.returncode == 0 and oa.get("cells") == ob.get("cells") == 0 and oa.get("noid") == want_noid and not ob.get("applied")
            and dc7 == DC7 and not os.path.exists(u7), f"X7 {name7} = 안 고침(점검·적용 같음 · 파일 무변 · 되돌림 파일 안 만듦)", (name7, oa, ob, rb.stderr[-300:]))
    else:
        rc = subprocess.run([sys.executable, TOOL, "--state", sd7, "--json"], env=env2, capture_output=True, text=True, timeout=120)
        ru = subprocess.run([sys.executable, TOOL, "--state", sd7, "--undo", u7], env=env2, capture_output=True, text=True, timeout=120)
        back = (json.load(open(os.path.join(sd7, "daily_px.json"), encoding="utf-8")), json.load(open(os.path.join(sd7, "daily_cache.json"), encoding="utf-8")))
        chk(oa.get("cells") == ob.get("cells") == 1 and oa["groups"]["7"]["src"] == [min(k for k in ents if k != OTHER)] and ob.get("applied") and dc7[DX]["val"] == 1010
            and json.loads(rc.stdout or "{}").get("cells") == 0 and ru.returncode == 0 and back == (DP7, DC7),
            f"X7 {name7} = 고침(4→1 · 4,010→1,010 · 다시 점검 0 · 되돌림 정확)", (oa, ob, dc7.get(DX), rc.stdout[-200:], ru.stdout[-200:]))

sd8 = os.path.join(T.TMP, "px8")
os.makedirs(sd8, exist_ok=True)
for name, obj in (("daily_close_px.json", {"_v": 1, "s": {"ca:eth:0xj": ENT7}}), ("curve_hist_px.json", {"_v": 1, "specs": {}}), ("daily_px.json", DP7),
                  ("daily_cache.json", DC7)):
    with open(os.path.join(sd8, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
mkledger(sd8)


def put8(name, obj):
    with open(os.path.join(sd8, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def now8():
    return json.load(open(os.path.join(sd8, "daily_px.json"), encoding="utf-8")), json.load(open(os.path.join(sd8, "daily_cache.json"), encoding="utf-8"))


u8 = os.path.join(sd8, "undo8.json")
r8 = subprocess.run([sys.executable, TOOL, "--state", sd8, "--apply", "--undo-out", u8], env=env2, capture_output=True, text=True, timeout=120)
DP8A, DC8A = now8()
chk(r8.returncode == 0 and DC8A[DX]["val"] == 1010 and DP8A[DX]["p"]["7"] == 1.0, "X8 (전제) 적용 = 두 파일 고침", (r8.stdout, r8.stderr[-300:]))
for name8, dp9, dc9 in (("두 번째 쓰기 실패(daily_px 만 고친 값)", DP8A, DC7), ("되돌림 중간 멈춤(daily_cache 만 고친 값)", DP7, DC8A)):
    put8("daily_px.json", dp9)
    put8("daily_cache.json", dc9)
    ru = subprocess.run([sys.executable, TOOL, "--state", sd8, "--undo", u8], env=env2, capture_output=True, text=True, timeout=120)
    chk(ru.returncode == 0 and now8() == (DP7, DC7), f"X8 {name8} = 기본 되돌림(새 프로세스)이 정확히 원래대로", (ru.returncode, ru.stdout[-300:]))
ed = json.loads(json.dumps(DC8A))
ed[DX]["val"] = 1234.5
put8("daily_px.json", DP8A)
put8("daily_cache.json", ed)
ru = subprocess.run([sys.executable, TOOL, "--state", sd8, "--undo", u8], env=env2, capture_output=True, text=True, timeout=120)
chk(ru.returncode == 2 and now8() == (DP8A, ed), "X8 한 파일이 고치기 전·후 밖의 값(다른 편집) = 그 날 건너뜀(종료값 2 · 파일 무변)", (ru.returncode, ru.stdout[-300:]))
ru = subprocess.run([sys.executable, TOOL, "--state", sd8, "--undo", u8, "--force"], env=env2, capture_output=True, text=True, timeout=120)
chk(ru.returncode == 0 and now8() == (DP7, DC7), "X8 --force = 그래도 원래대로(종전)", ru.stdout[-300:])
T.finish()
