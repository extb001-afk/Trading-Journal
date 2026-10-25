#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
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
for name, obj in (("daily_close_px.json", dcs), ("curve_hist_px.json", hp), ("daily_px.json", dpx), ("daily_cache.json", dcache)):
    with open(os.path.join(SD, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)


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
    and o["groups"]["7"]["usd_digits"] == "10^3" and not o.get("applied"), "X1 점검 = 그룹 7(7일 · 하루 최대 10^3) · 격리 99 · 근거 강한 8 제외", (o, r.stderr[-400:]))
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
r6 = subprocess.run([sys.executable, TOOL, "--state", SD6, "--json"], env=env2, capture_output=True, text=True, timeout=120)
try:
    o6 = json.loads(r6.stdout)
except ValueError:
    o6 = {}
chk(r6.returncode == 0 and o6.get("cells") == 11 and (o6.get("groups") or {}).get("7", {}).get("days") == 6,
    "X6 같은 날 같은 값이 다른 출처 키 둘 = 안 고침(그 날만 빠짐 · 13→11칸) · 같은 키가 두 저장본에 있으면 한 출처(종전)", (o6, r6.stderr[-300:]))
T.finish()
