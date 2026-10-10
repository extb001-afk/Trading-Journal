#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import re
import subprocess
import time

for _k in ("TJ_NODEREAL_KEY", "TJ_ANKR_KEY", "TJ_QUICKNODE_BSC_KEY", "TJ_QUICKNODE_BASE_KEY", "TJ_ALCHEMY_KEY"):
    os.environ.pop(_k, None)
W1 = "0x" + "1a" * 20
W2 = "0x" + "2b" * 20
SOLW = "So1TestOwner1111111111111111111111111111111"
CFG = {"wallets": [{"type": "evm", "chain": "eth", "address": W1, "label": "시험1"},
                   {"type": "evm", "chain": "base", "address": W2, "label": "시험2"}],
       "chains": {"eth": {"etherscan_chainid": 1}, "base": {"blockscout": "https://base-explorer.invalid"}},
       "backfill_months": 0}
CP = os.path.join(T.TMP, "config.json")
with open(CP, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
os.environ["TJ_CONFIG"] = CP
import common

assert T.TMP in common.STATE_DIR
import addr_tier as AT

DAY = 86400
NOW = time.time()


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else d)


def book(scope="eth", path="etherscan", ws=(W1,), poll=45.0, cfg=None, sent_days=200, code="eoa"):
    for f in os.listdir(common.STATE_DIR):
        if f.startswith("addr_tier_") and f != AT.REQ_PATH_NAME:
            os.remove(os.path.join(common.STATE_DIR, f))
    b = AT.TierBook(scope, cfg if cfg is not None else {"backfill_months": 0}, poll, path, list(ws))
    b.set_boot({}, "test")
    for w in ws:
        b.set_code(w, code)
        b.note_sent(w, int(NOW - sent_days * DAY))
    return b


st = AT.settings({})
steps = AT.parse_steps(AT.DEFAULT_STEPS)
check("A1a 기본 받침 확인(backstop_sec) = 1시간", st["backstop_sec"] == 3600, st["backstop_sec"])
check("A1b 기본 계단 = 쉬는 칸 활동 점검 간격 전부 ≤ 10분(초 단위 칸)",
      all(v <= 600 for _lim, (k, v) in steps if k == "s") and steps[-1][0] is None, steps)
check("A1c 계단 라벨 수 = 계단 수", len(AT.TIER_LABELS) == len(steps), (AT.TIER_LABELS, steps))
check("A1d 빈 지갑 = 활동 점검 ≤ 10분 · 받침 확인 ≤ 1시간", AT.EMPTY_ACT_SEC <= 600 and AT.EMPTY_BACKSTOP_SEC <= 3600,
      (AT.EMPTY_ACT_SEC, AT.EMPTY_BACKSTOP_SEC))
for days in (10, 45, 120, 200, 800):
    b = book(sent_days=days)
    t, iv, why = b.tier(W1)
    bs = b.backstop_of(iv, t, W1) if iv > 0 else None
    check(f"A1e {days}일 쉰 지갑 = 쉬는 칸 · 활동 점검 ≤ 10분 · 탐색기 확인 ≤ 1시간", why is None and t > 0 and 0 < iv <= 600 and bs is not None and bs <= 3600,
          (t, iv, why, bs))
b = book(sent_days=20)
b.period = 900
t, iv, why = b.tier(W1)
check("A2a 기본 주기 P = 15분이어도 활동 점검 ≤ 10분 · 확인 ≤ 1시간", 0 < iv <= 600 and b.backstop_of(iv, t, W1) <= 3600, (t, iv, b.backstop_of(iv, t, W1)))
b = book(cfg={"backfill_months": 0, "addr_tier": {"steps": [[7, "x1"], [30, "x5"], [None, 86400]], "backstop_sec": 21600}})
t, iv, why = b.tier(W1)
check("A2b 설정 계단이 하루·받침 6시간이어도 상한(10분 · 1시간)", 0 < iv <= 600 and b.backstop_of(iv, t, W1) <= 3600, (t, iv, b.backstop_of(iv, t, W1)))
b = book()
b.mark_empty(W1, 100)
t, iv, why = b.tier(W1)
check("A2c 빈 지갑 = 활동 점검 ≤ 10분 · 받침 확인 ≤ 1시간", b.is_empty(W1) and 0 < iv <= 600 and b.backstop_of(iv, t, W1) <= 3600,
      (b.is_empty(W1), iv, b.backstop_of(iv, t, W1)))
b.stretch = 4.0
t4, iv4, _w = b.tier(W1)
check("A3a 예산 넘침 배수 = 빈 지갑 확인 간격도 배수만큼(1시간 × 4)", b.backstop_of(iv4, t4, W1) == 4 * 3600 and iv4 == 4 * iv, (iv4, b.backstop_of(iv4, t4, W1)))
b = book(sent_days=200)
b.stretch = 3.0
t, iv, why = b.tier(W1)
check("A3b 예산 넘침 배수 = 쉬는 쌍 간격도 배수만큼(10분·1시간 × 3)", iv == 1800 and b.backstop_of(iv, t, W1) == 3 * 3600, (iv, b.backstop_of(iv, t, W1)))
ws500 = ["0x" + ("%040x" % (0xabc000 + i)) for i in range(500)]
b5 = book(ws=ws500, poll=45.0, sent_days=1)
ps = AT.plan_stretch([b5], {"backfill_months": 0})
check("A3c 지갑 500개 = 예산 맞춤(기본 주기 늘림·넘침 단계) 작동", (ps.get("period") or 1) > 1 or ps.get("gate") or ps.get("stretch", 1) > 1, ps)
b5.stretch, b5.gate_t0, b5.period = 1.0, False, None

b = book(ws=(W1, W2), sent_days=200)
for w in (W1, W2):
    b.note_full(w, 1000, NOW - (3700 if w == W1 else 1800))
    b.note_baseline(w, 5, 7, 1000)
due, rest = b.due_list([W1, W2], now=NOW)
check("A4a 받침 기한 1시간 지난 쌍 = 이번 주기 탐색기 확인 · 30분 된 쌍 = 쉼", W1 in due and W2 in rest, (due, rest))
with b.lock:
    b.pairs[W1]["actAt"] = int(NOW - 700)
    b.pairs[W2]["actAt"] = int(NOW - 100)
tg = b.activity_targets(now=NOW)
check("A4b 활동 점검 = 10분 넘은 쌍만", W1 in tg and W2 not in tg, tg)
b = book(ws=ws500, poll=300.0, sent_days=200)
for w in ws500:
    b.note_full(w, 1000, NOW - 60)
    b.note_baseline(w, 1, 1, 1000)
    b.pairs[w]["actAt"] = int(NOW - 700)
tg = b.activity_targets(now=NOW)
check("A4c 쉬는 쌍 500개 · 수집 주기 5분 = 주기당 점검 상한이 10분 안에 다 돌 만큼(≥ 250)", len(tg) >= 250, len(tg))

b = book(ws=ws500, poll=300.0, sent_days=200)
T0 = NOW
for i, w in enumerate(ws500):
    b.note_full(w, 1000, T0 - 3600.0 * i / len(ws500))
    b.note_baseline(w, 1, 1, 1000)
worst = 0.0
for k in range(36):
    tk = T0 + 300.0 * k
    due9, _r9 = b.due_list(ws500, now=tk)
    if k >= 12:
        worst = max(worst, max(tk - float(b.pairs[w]["full"]) for w in ws500))
    for w in due9:
        b.note_full(w, 1000, tk)
check("A4d 받침 확인 = 쉬는 쌍 500개 · 주기 5분에서도 1시간(+ 한 주기) 안", worst <= 3600 + 300 + 1, round(worst))

SEL_AGG = "252dba42"


def mc_result(blk, bals):
    n = len(bals)
    words = ["%064x" % blk, "%064x" % 64, "%064x" % n]
    words += ["%064x" % (32 * n + 64 * k) for k in range(n)]
    for v in bals:
        words += ["%064x" % 32, "%064x" % v]
    return "0x" + "".join(words)


def mc_addrs(data):
    body = data[2 + 8:]
    n = int(body[64:128], 16)
    out = []
    for k in range(n):
        off = int(body[128 + 64 * k:128 + 64 * (k + 1)], 16) * 2 + 128
        cd = body[off + 64 * 3:off + 64 * 3 + 72]
        out.append("0x" + cd[8 + 24:8 + 64])
    return out


class WT:
    chain = "eth"
    conf_depth = 12
    cfg_rpcs = ["https://rpc.invalid"]
    RPC_DEFAULT = {}

    def __init__(self, ws):
        self.wallets = list(ws)
        self.cursor = {w: 1000 for w in ws}


CALLS = []
BAL = {}
MODE = {"mc": "ok"}


def fake_rpc(wt, method, params):
    CALLS.append(method)
    if method == "eth_blockNumber":
        return hex(2000 + 12)
    if method == "eth_call":
        if MODE["mc"] == "empty":
            return "0x"
        d = params[0]["data"]
        assert d[2:10] == SEL_AGG, d[:12]
        return mc_result(int(params[1], 16), [BAL.get(a, 7) for a in mc_addrs(d)])
    if method == "eth_getTransactionCount":
        return hex(5)
    if method == "eth_getBalance":
        return hex(BAL.get(params[0], 7))
    if method == "eth_getCode":
        return "0x"
    raise AssertionError(method)


ws100 = ["0x" + ("%040x" % (0xdef000 + i)) for i in range(100)]
AT.RPC_IMPL = fake_rpc
try:
    b = book(ws=ws100, poll=45.0, sent_days=200)
    b.mc = getattr(AT, "MULTICALL3", "0xca11bde05977b3631167028862be2a173976ca11")
    for w in ws100:
        b.note_full(w, 1000, NOW - 60)
        b.note_baseline(w, 5, 7, 1000)
        b.pairs[w]["actAt"] = int(NOW - 700)
        b.pairs[w]["codeAt"] = int(NOW)
        b.pairs[w]["cov"] = int(NOW - 400 * DAY)
    BAL.clear()
    BAL[ws100[3]] = 9
    CALLS.clear()
    wt = WT(ws100)
    AT.evm_activity(wt, b)
    check("A5a 쉬는 쌍 100개 활동 점검 = eth_blockNumber 1 + Multicall3 eth_call 1(쌍별 nonce·잔고 0)",
          CALLS == ["eth_blockNumber", "eth_call"], CALLS[:8])
    woke = [w for w in ws100 if isinstance(b.pairs[w].get("wake"), dict)]
    check("A5b 잔고 바뀐 쌍만 깨움", woke == [ws100[3]], woke[:5])
    check("A5c 점검 시각 기록(다음 점검 = 10분 뒤)", all(int(b.pairs[w].get("actAt") or 0) >= int(NOW) - 1 for w in ws100))
    for w in ws100:
        b.pairs[w].pop("wake", None)
        b.pairs[w]["actAt"] = int(NOW - 700)
    MODE["mc"] = "empty"
    CALLS.clear()
    b.st["probe_max_per_cycle"] = 10
    AT.evm_activity(wt, b, deadline=time.time() + 30)
    check("A5d Multicall3 없음(빈 응답) = 그 주기 쌍별 nonce·잔고로", "eth_getTransactionCount" in CALLS and "eth_getBalance" in CALLS, CALLS[:8])
    CALLS.clear()
    for w in ws100:
        b.pairs[w]["actAt"] = int(NOW - 700)
    AT.evm_activity(wt, b, deadline=time.time() + 30)
    check("A5e 없음이 확인된 체인은 다음 주기 Multicall 안 부름", "eth_call" not in CALLS and "eth_getBalance" in CALLS, CALLS[:8])
    MODE["mc"] = "ok"
finally:
    AT.RPC_IMPL = None

bs_ = book(scope="sol", path="helius", ws=(SOLW,), poll=60.0, sent_days=300)
t, iv, why = bs_.tier(SOLW)
check("A6a 솔라나 쉬는 소유자 = 서명 확인 ≤ 10분 · ATA 받침 ≤ 1시간", why is None and 0 < iv <= 600 and bs_.backstop_of(iv, t, SOLW) <= 3600, (t, iv, why))
b = book(ws=(W1,), sent_days=200)
sm = b.summary()
check("A6b 요약 하루 탐색기 확인 ≈ 24회(1시간마다) + 깨움 추정", 24 <= sm["fullPerDay"] <= 26, sm)
check("A6c 요약 활동 점검 = 하루 144회(10분마다)", 140 <= sm["actPerDay"] <= 145, sm)
b.save(force=True)
d = common.read_json(AT.state_path("eth"), {})
d["pairs"][W1]["tier"] = 4
common.atomic_write_json(AT.state_path("eth"), d)
wv = AT.web_view(dict(CFG))
check("A6d 화면 계단 표 = 라벨 수 · 옛 장부 계단 번호는 마지막 칸으로", len(wv["steps"]) == len(AT.TIER_LABELS)
      and all(0 <= p["t"] < len(AT.TIER_LABELS) for p in wv["addrs"].get(W1, [])), (wv["steps"], wv["addrs"].get(W1)))
check("A6e 화면 받침 확인 = 1시간", wv.get("backstopSec") == 3600, wv.get("backstopSec"))

SJ = open(os.path.join(T.ROOT, "web", "v2", "setup.js"), encoding="utf-8").read()
m = re.search(r"const TIER_SHORT = \[([^\]]*)\]", SJ)
ts_js = re.findall(r"'([^']*)'", m.group(1)) if m else None
check("A7a setup.js 계단 라벨 = 서버 라벨", ts_js == list(AT.TIER_LABELS), (ts_js, AT.TIER_LABELS))
for old in ("'빈 지갑 · 하루 1회'", "6개월 넘게 안 쓴 주소 = 최대 약 하루 늦게", "받침 확인(6시간, 6개월↑ 하루)", "활동은 하루 한 번 확인해요(토큰 입금만 오면 주 1회", "cnt = [0, 0, 0, 0, 0]"):
    check(f"A7b 옛 문구 없음: {old[:24]}", old not in SJ)
import demo_data

bk9, ad9 = demo_data._tier_books(NOW)
check("A7c 데모 장부 계단 칸 수 = 계단 수 · 칸 번호 범위 안", all(len(x["summary"]["tiers"]) == len(AT.TIER_LABELS) for x in bk9.values())
      and all(0 <= p["t"] < len(AT.TIER_LABELS) for ps9 in ad9.values() for p in ps9), [x["summary"]["tiers"] for x in bk9.values()])
import health

check("A7d 헬스 '쉬는 쌍 느린 확인 대기' 상한 ≤ 13시간(1시간 × 넘침 배수 12 + 여유)", health.REST_LATE_MAX <= 13 * 3600, health.REST_LATE_MAX)

RQ = AT.req_path()
for f in (RQ,):
    if os.path.exists(f):
        os.remove(f)
rw = getattr(AT, "request_wake", None)
check("B1a 도우미 request_wake 있음", callable(rw))
if callable(rw):
    r = rw([("base", W2)])
    reqs = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    check("B1b 요청 = '<체인>:<주소>' 시각", isinstance(reqs.get(f"base:{W2}"), int) and abs(reqs[f"base:{W2}"] - time.time()) < 5, reqs)
    t0 = reqs.get(f"base:{W2}")
    mt0 = os.path.getmtime(RQ)
    r2 = rw([("base", W2)])
    reqs2 = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    check("B1c 같은 키 10분 안 다시 = 안 씀(시각 그대로)", reqs2.get(f"base:{W2}") == t0 and os.path.getmtime(RQ) == mt0, (r2, reqs2))
    d = common.read_json(RQ, {})
    d["reqs"][f"base:{W2}"] = int(time.time()) - 601
    common.atomic_write_json(RQ, d)
    rw([("base", W2)])
    reqs3 = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    check("B1d 10분 지나면 다시 요청", reqs3.get(f"base:{W2}", 0) >= int(time.time()) - 5, reqs3)
    AT.request_check(W1)
    rw([("eth", W1)])
    reqs4 = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    check("B2a '지금 확인'·깨움 키가 서로 덮어쓰지 않음", f"*:{W1}" in reqs4 and f"eth:{W1}" in reqs4 and f"base:{W2}" in reqs4, reqs4)
    code = ("import sys,os;sys.path.insert(0,os.environ['TJ_TSRC']);import addr_tier as A\n"
            "p=sys.argv[1]\nfor i in range(40):\n    A.request_wake([('eth','0x%s%038x'%(p,i))])\n")
    env = dict(os.environ, TJ_TSRC=T.SRC)
    procs = [subprocess.Popen([sys.executable, "-c", code, p], env=env) for p in ("aa", "bb")]
    rcs = [p.wait(60) for p in procs]
    reqs5 = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    got = sum(1 for k in reqs5 if k.startswith("eth:0xaa") or k.startswith("eth:0xbb"))
    check("B2b 두 프로세스 동시 깨움 80건 = 유실 0", rcs == [0, 0] and got == 80, (rcs, got))

    import fcntl
    import threading
    with open(RQ + ".lock", "a") as lf9:
        fcntl.flock(lf9, fcntl.LOCK_EX)
        t9 = time.time()
        out = subprocess.run([sys.executable, "-c", code.replace("for i in range(40):", "for i in range(1):") + "print(A.request_wake([('eth','0x' + 'cd' * 20)]))\n", "cc"],
                             env=env, capture_output=True, text=True, timeout=30)
        el9 = time.time() - t9
    check("B2c 다른 프로세스가 파일 잠금을 쥐고 있으면 2초 안에 건너뜀(무한 대기 없음)", el9 < 10 and "'ok': False" in out.stdout, (round(el9, 1), out.stdout[-200:], out.stderr[-300:]))
    AT._REQ_LOCK.acquire()
    try:
        t9 = time.time()
        r9 = AT.request_wake([("eth", "0x" + "ce" * 20)])
        el9 = time.time() - t9
    finally:
        AT._REQ_LOCK.release()
    check("B2d 프로세스 안 잠금이 쥐어져 있어도 2초 안에 건너뜀", el9 < 3.5 and r9.get("ok") is False, (round(el9, 1), r9))

    os.remove(RQ)
    b = book(scope="base", path="blockscout", ws=(W2,), sent_days=300)
    b.note_full(W2, 1000, NOW - 60)
    b.note_baseline(W2, 1, 1, 1000)
    due, rest = b.due_list([W2])
    check("B3a 깨우기 전 = 쉼", W2 in rest, (due, rest))
    rw([("base", W2)])
    b._req_cache = (None, {})
    due, rest = b.due_list([W2])
    check("B3b 깨운 뒤 = 이번 주기 탐색기 확인(req)", W2 in due and b.hold_reason(W2) == "req", (due, rest, b.hold_reason(W2)))
    time.sleep(1.1)
    b.note_full(W2, 1100)
    b.note_baseline(W2, 1, 1, 1100)
    due, rest = b.due_list([W2])
    check("B3c 확인 끝(note_full) = 다시 쉼", W2 in rest and b.hold_reason(W2) is None, (due, rest, b.hold_reason(W2)))

import web

SB = web.StateBuilder
wk = getattr(SB, "_wd_transit_wake", None)
check("B4a 빌더 훅 _wd_transit_wake 있음", callable(wk))
if callable(wk) and callable(rw):
    if os.path.exists(RQ):
        os.remove(RQ)
    sb = object.__new__(SB)
    SOLD = "So1Dest1111111111111111111111111111111111111"
    ents = [{"state": "pending", "own": True, "cls": "wallet", "addr": W2, "net": "BASE", "sym": "USDC", "ex": "binance"},
            {"state": "pending", "own": True, "cls": "wallet", "addr": W1.upper().replace("0X", "0x"), "net": "ERC20", "sym": "USDC", "ex": "upbit"},
            {"state": "pending", "own": True, "cls": "wallet", "addr": SOLD, "net": "SOL", "sym": "SOL", "ex": "upbit"},
            {"state": "arrived", "own": True, "cls": "wallet", "addr": "0x" + "3c" * 20, "net": "BASE", "sym": "USDC", "ex": "binance"},
            {"state": "out", "own": True, "cls": "wallet", "addr": "0x" + "4d" * 20, "net": "BASE", "sym": "USDC", "ex": "binance", "why": "expired"},
            {"state": "cancel", "own": True, "cls": "wallet", "addr": "0x" + "5e" * 20, "net": "BASE", "sym": "USDC", "ex": "binance"},
            {"state": "pending", "own": True, "cls": "exchange", "addr": "0x" + "6f" * 20, "net": "BASE", "sym": "USDC", "ex": "binance"},
            {"state": "pending", "own": True, "cls": "wallet_untracked", "addr": "0x" + "7a" * 20, "net": "PHAROS", "sym": "USDC", "ex": "binance"},
            {"state": "pending", "own": False, "cls": "unknown", "addr": "0x" + "8b" * 20, "net": "BASE", "sym": "USDC", "ex": "binance"},
            {"state": "pending", "own": True, "cls": None, "verdict": "own", "addr": "0x" + "9c" * 20, "net": "WEIRDNET", "sym": "USDC", "ex": "binance",
             "_reg": True}]
    sb._hist_wallets = lambda: [{"address": W1}, {"address": W2}, {"address": SOLD}, {"address": "0x" + "9c" * 20}]
    keys = SB._wd_transit_wake(sb, ents)
    reqs = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    want = {f"base:{W2}", f"eth:{W1}", f"sol:{SOLD}", "*:0x" + "9c" * 20}
    check("B4b 전송 중 · 내 등록 지갑(수집 중 체인)만 깨움 — 체인 = 출금 네트워크 · 네트워크 모름 = 주소 전체(*)", set(reqs) == want, sorted(reqs))
    check("B4c 도착·나감·취소·거래소행·미추적·남의 주소 = 안 깨움", not any(("3c" * 20) in k or ("4d" * 20) in k or ("5e" * 20) in k or ("6f" * 20) in k
                                                               or ("7a" * 20) in k or ("8b" * 20) in k for k in reqs), sorted(reqs))
    mt1 = os.path.getmtime(RQ)
    SB._wd_transit_wake(sb, ents)
    check("B4d 빌드마다 불려도 10분 안 = 다시 안 씀", os.path.getmtime(RQ) == mt1)
    os.remove(RQ)
    TX = "0x" + "ee" * 32
    sb.cfg = {}
    sb.outflow_decisions = lambda: {}
    sb._wd_cls_fn = lambda p: ("wallet", None)
    wd = [{"ex": "binance", "uuid": "u1", "ts": int(NOW - 3600), "sym": "USDC", "qty": web.Decimal("8800"), "txid": TX, "gid": 1,
           "known": web.Decimal(0), "cost": web.Decimal(0)}]
    raw = {("binance", "u1"): {"state": "DONE", "address": W2, "network": "BASE", "txid": TX, "currency": "USDC", "done_at": None}}
    out = SB._wd_transit_resolve(sb, wd, [], raw, {}, {}, {}, {}, {}, now=NOW)
    check("B5a 도착 기장 전 = 전송 중(내 지갑)", out and out[0]["state"] == "pending" and out[0]["own"], out)
    SB._wd_transit_wake(sb, out)
    reqs = (common.read_json(RQ, {}) or {}).get("reqs") or {}
    check("B5b 전송 중 = 받는 주소 깨움(base)", f"base:{W2}" in reqs, reqs)
    os.remove(RQ)
    rows = [{"event": "TRANSFER_IN", "leg_kind": "acq", "source_id": TX, "event_ts": int(NOW - 60), "location": f"wallet:base:{W2}",
             "group_id": 1, "asset_id": 1, "symbol": "USDC"}]
    wd2 = [{k: v for k, v in wd[0].items() if k in ("ex", "uuid", "ts", "sym", "qty", "txid", "gid", "known", "cost")}]
    out2 = SB._wd_transit_resolve(sb, wd2, rows, raw, {}, {}, {}, {}, {}, now=NOW)
    check("B5c 같은 txid 유입 기장 = 도착(전송 중 가산 없음)", out2 and out2[0]["state"] == "arrived", out2)
    SB._wd_transit_wake(sb, out2)
    check("B5d 도착 = 깨움 멈춤(요청 0)", not os.path.exists(RQ) or not ((common.read_json(RQ, {}) or {}).get("reqs")), common.read_json(RQ, {}))

if callable(wk):
    TX6 = "0x" + "e6" * 32
    sb6 = object.__new__(SB)
    sb6.cfg = {}
    sb6.outflow_decisions = lambda: {}
    sb6._hist_wallets = lambda: [{"address": W2}]
    HD = os.path.join(common.STATE_DIR, "health")
    os.makedirs(HD, exist_ok=True)

    def clear6():
        for f9 in (os.path.join(common.STATE_DIR, "cursor_evm_base.json"), os.path.join(HD, "evm.json"), AT.state_path("base")):
            if os.path.exists(f9):
                os.remove(f9)

    def res6(age_h, cls=("wallet", None), net="BASE"):
        sb6._wd_cls_fn = lambda p, c=cls: c
        wd6 = [{"ex": "binance", "uuid": "u6", "ts": int(NOW - age_h * 3600), "sym": "USDC", "qty": web.Decimal("8800"), "txid": TX6, "gid": 1,
                "known": web.Decimal(0), "cost": web.Decimal(0)}]
        raw6 = {("binance", "u6"): {"state": "DONE", "address": W2, "network": net, "txid": TX6, "currency": "USDC", "done_at": None}}
        o = SB._wd_transit_resolve(sb6, wd6, [], raw6, {}, {}, {}, {}, {}, now=NOW)
        return o[0] if o else {}

    clear6()
    e6 = res6(50)
    check("B6a 내 지갑행 50시간 · 받는 체인 수집 진행 모름 = 전송 중 유지(받는 쪽 기록 확인 중)", e6.get("state") == "pending" and e6.get("why") == "cover", e6.get("state"))
    loc6 = SB._transit_loc(dict(e6, src="바이낸스", qty=web.Decimal("8800"), uuid="u6"), NOW) if e6.get("state") == "pending" else {}
    check("B6b 위치 문구 = '받는 쪽 기록 확인 중'", "받는 쪽 기록 확인 중" in str(loc6.get("sub")), loc6)
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"), {W2: 1000})
    common.atomic_write_json(os.path.join(HD, "evm.json"), {"schema": 1, "unit": "evm", "ts": int(NOW), "sources": {
        "base": {"head": 1000 + 60 * 3600, "block_sec_est": 2.0, "last_cycle_ts": int(NOW), "last_success_ts": int(NOW)}}})
    e6 = res6(50)
    check("B6c 받는 지갑 커서가 출금 시각보다 뒤(120시간 전 블록) = 전송 중 유지", e6.get("state") == "pending" and e6.get("why") == "cover", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(os.path.join(HD, "evm.json"), {"schema": 1, "unit": "evm", "ts": int(NOW), "sources": {
        "base": {"head": 1010, "block_sec_est": 2.0, "last_cycle_ts": int(NOW), "last_success_ts": int(NOW)}}})
    e6 = res6(50)
    check("B6d 받는 지갑 커서가 출금 + 여유를 넘음(20초 전 블록) = 종전대로 '나감'(창 지남)", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    clear6()
    common.atomic_write_json(AT.state_path("base"), {"scope": "base", "updatedAt": int(NOW), "pairs": {W2: {"full": int(NOW - 120)}}})
    e6 = res6(50)
    check("B6e 계단 장부 마지막 확인(2분 전)이 출금 뒤 = '나감'", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(AT.state_path("base"), {"scope": "base", "updatedAt": int(NOW), "pairs": {W2: {"full": int(NOW - 51 * 3600)}}})
    e6 = res6(50)
    check("B6f 계단 장부 마지막 확인이 출금 전 = 전송 중 유지", e6.get("state") == "pending" and e6.get("why") == "cover", (e6.get("state"), e6.get("why")))
    clear6()
    e6 = res6(8 * 24)
    check("B6g 상한(7일) 넘으면 수집 진행 몰라도 종전대로 '나감'", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    e6 = res6(50, cls=("exchange", "upbit"))
    check("B6h 거래소행(내 지갑 아님)은 종전대로 48시간 뒤 '나감'", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    e6 = res6(5)
    check("B6i 창 안(5시간)은 종전대로 전송 중(사유 없음)", e6.get("state") == "pending" and not e6.get("why"), (e6.get("state"), e6.get("why")))
    H7 = 50_000_000

    def hb7(success_ago_s=0, cycle_ago_s=0, head=H7, unit="evm", chain="base", cursor=None):
        src = {"head": head, "block_sec_est": 2.0, "last_cycle_ts": int(NOW - cycle_ago_s), "last_success_ts": int(NOW - success_ago_s)}
        if cursor is not None:
            src["cursor"] = cursor
        common.atomic_write_json(os.path.join(HD, unit + ".json"), {"schema": 1, "unit": unit, "ts": int(NOW), "sources": {chain: src}})

    def blk(ago_h):
        return H7 - int(ago_h * 3600 / 2)

    clear6()
    hb7()
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"),
                             {W2: blk(1 / 60), "_bk:" + W2: {"from": blk(200), "to": blk(1 / 60), "done": blk(60), "why": "new"}})
    e6 = res6(50)
    check("B7a 차선 모드: 라이브 커서는 1분 전이지만 뒤 차선 진행점이 60시간 전(출금 50시간 전 미수집) = 유예 유지", e6.get("state") == "pending" and e6.get("why") == "cover",
          (e6.get("state"), e6.get("why")))
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"),
                             {W2: blk(1 / 60), "_bk:" + W2: {"from": blk(200), "to": blk(1 / 60), "done": blk(40), "why": "new"}})
    e6 = res6(50)
    check("B7b 뒤 차선이 출금 + 여유(40시간 전)까지 끝남 = '나감'", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"),
                             {W2: blk(1 / 60), "_bk:" + W2: {"from": blk(200), "to": blk(55), "done": blk(150), "why": "new"}})
    e6 = res6(50)
    check("B7c 차선 나뉜 뒤(55시간 전)의 출금 = 라이브 커서가 덮음 = '나감'", e6.get("state") == "out" and e6.get("why") == "expired", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"), {W2: H7})
    hb7(success_ago_s=60 * 3600, cycle_ago_s=0)
    e6 = res6(50)
    check("B7d 마지막 성공 60시간 전 · 그 뒤 실패 주기만(last_cycle 지금) = 유예 유지(성공 시각 기준)", e6.get("state") == "pending" and e6.get("why") == "cover",
          (e6.get("state"), e6.get("why")))
    hb7(success_ago_s=60, cycle_ago_s=0)
    e6 = res6(50)
    check("B7e 마지막 성공 1분 전 = '나감'", e6.get("state") == "out", e6.get("state"))
    common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_base.json"),
                             {W2: H7, "_bk:" + W2: {"from": blk(200), "to": blk(1 / 60), "done": blk(60), "why": "new"}})
    common.atomic_write_json(AT.state_path("base"), {"scope": "base", "updatedAt": int(NOW), "pairs": {W2: {"full": int(NOW - 120)}}})
    e6 = res6(50)
    check("B7f 계단 장부 확인 시각이 최근이어도 뒤 차선 미완(출금 구간) = 유예 유지", e6.get("state") == "pending" and e6.get("why") == "cover", (e6.get("state"), e6.get("why")))
    clear6()
    bscp = os.path.join(common.STATE_DIR, "cursor_bsc.json")
    hb7(unit="bsc", chain="bsc", cursor=H7)
    common.atomic_write_json(bscp, {"_wallets": [], "head": H7})
    e6 = res6(50, net="BSC")
    check("B7g BSC 커서 지갑 목록에 없음(새 지갑) = 유예 유지", e6.get("state") == "pending" and e6.get("why") == "cover", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(bscp, {"_wallets": [W2], "_neww": {"wallets": [W2]}, "head": H7})
    e6 = res6(50, net="BSC")
    check("B7h BSC 새 지갑 백필 대상 = 유예 유지", e6.get("state") == "pending" and e6.get("why") == "cover", (e6.get("state"), e6.get("why")))
    common.atomic_write_json(bscp, {"_wallets": [W2], "head": H7})
    e6 = res6(50, net="BSC")
    check("B7i BSC 커서 지갑 · 커서가 지금 = '나감'", e6.get("state") == "out", e6.get("state"))
    os.remove(bscp)
    os.remove(os.path.join(HD, "bsc.json"))

import settings_store as ss
import onboarding
import bf_engine

na = getattr(ss, "needs_ankr", None)
check("C1a settings_store.needs_ankr 있음", callable(na))
if callable(na):
    check("C1b EVM 지갑 있음 = Ankr 필수 · 없음 = 아님", na(CFG) is True and na({"wallets": [{"type": "sol", "address": SOLW}]}) is False and na({}) is False)
st = onboarding.status()
check("C1c 설정 상태 evmNeedsAnkr = True · ankr 미설정", st.get("evmNeedsAnkr") is True and (st.get("explorers") or {}).get("ankr", {}).get("set") is False,
      (st.get("evmNeedsAnkr"), (st.get("explorers") or {}).get("ankr")))
kk = health.collect_keys(CFG)
check("C1d 헬스 키 관측 = ankr 필요·없음(값 없음)", kk.get("ankrNeed") is True and kk.get("ankr") is False, kk)
hh = dict(health.DEFAULTS, units=["tj-evm"])


def kcard(obs_keys):
    cs = [c for c in health.evaluate({"now": time.time(), "keys": obs_keys}, hh) if c["id"] == "key:ankr"]
    return cs[0] if cs else None


c1 = kcard(dict(kk))
check("C1e EVM 지갑 + Ankr 키 없음 = 주의 카드(알림 아님) · 설정 안내", c1 and c1["level"] == "warn" and c1["notify"] is False and "ankr.com" in c1["action"], c1)
c2 = kcard(dict(kk, ankr=True))
check("C1f Ankr 키 있음 = 정상", c2 and c2["level"] == "ok", c2)
check("C1g EVM 지갑 없음·옛 서버 관측(칸 없음) = 카드 없음", kcard(dict(kk, ankrNeed=False)) is None and kcard({"evm": True, "etherscan": True}) is None)
AJ = open(os.path.join(T.ROOT, "web", "v2", "app.js"), encoding="utf-8").read()
HJ = open(os.path.join(T.ROOT, "web", "v2", "health.js"), encoding="utf-8").read()
check("C2a setup.js Ankr 배너·필수 배지·요약 줄", "function ankrBanner" in SJ and "evmNeedsAnkr" in SJ and "k === 'ankr'" in SJ, "")
check("C2b app.js 처음 설정 안내·빈 키에 Ankr", "evmNeedsAnkr" in AJ and "'Ankr'" in AJ, "")
check("C2c health.js 키 바로가기 key:ankr", "'key:ankr'" in HJ, "")
RD = open(T.README, encoding="utf-8").read()
AK_DOC = open(os.path.join(os.path.dirname(T.README), "docs", "API_KEYS.md"), encoding="utf-8").read()
ENVX = open(os.path.join(os.path.dirname(T.README), ".env.example"), encoding="utf-8").read()
check("C2d README 키 표 Ankr = EVM 필수", re.search(r"`TJ_ANKR_KEY` \| EVM 지갑이 있으면 \*\*필수\*\*", RD) is not None, "")
check("C2e API_KEYS Ankr = 필수", "## Ankr — `TJ_ANKR_KEY` (EVM 지갑이 있으면 필수" in AK_DOC, "")
check("C2f .env.example Ankr = 필수 주석", re.search(r"EVM 지갑이 있으면 필수[^\n]*\n(#[^\n]*\n)*TJ_ANKR_KEY=", ENVX) is not None and ENVX.count("EVM 지갑이 있으면 필수") >= 2, "")

AKEY = "a" * 64
NODE_CALLS = []


def node_rpc_ok(u, m, p, timeout=15.0):
    NODE_CALLS.append((u, m))
    return "0x10"


def node_rpc_err(kind, code=None):
    def f(u, m, p, timeout=15.0):
        NODE_CALLS.append((u, m))
        raise bf_engine.NetError("시험 오류", kind, code=code)
    return f


real_node_rpc = onboarding._node_rpc
real_http = onboarding._http
try:
    for code, name in ((401, "C3a"), (403, "C3b"), (404, "C3c")):
        if os.path.exists(common.ENV_PATH):
            os.remove(common.ENV_PATH)
        NODE_CALLS.clear()
        onboarding._node_rpc = node_rpc_err("http4xx", code)
        onboarding.RL.reset() if hasattr(onboarding.RL, "reset") else None
        r = onboarding._dispatch("keys/save", {"group": "ankr", "values": {"TJ_ANKR_KEY": AKEY}})
        check(f"{name} Ankr 키 HTTP {code} = 저장 안 함 · 1콜(eth_blockNumber) · 키 값 응답에 없음",
              r.get("ok") is False and not ss.read_env().get("TJ_ANKR_KEY") and [m for _u, m in NODE_CALLS] == ["eth_blockNumber"]
              and AKEY not in json.dumps(r, ensure_ascii=False), (r, NODE_CALLS))
    NODE_CALLS.clear()
    onboarding._node_rpc = node_rpc_err("conn")
    r = onboarding._dispatch("keys/save", {"group": "ankr", "values": {"TJ_ANKR_KEY": AKEY}})
    check("C3d 연결 실패 = 저장 + 경고(note)", r.get("ok") is True and ss.read_env().get("TJ_ANKR_KEY") == AKEY and r.get("note"), r)
    NODE_CALLS.clear()
    onboarding._node_rpc = node_rpc_ok
    r = onboarding._dispatch("keys/save", {"group": "ankr", "values": {"TJ_ANKR_KEY": AKEY}})
    check("C3e 정상 = 저장 · 경고 없음 · Ankr 이더리움 노드 1콜", r.get("ok") is True and not r.get("note") and len(NODE_CALLS) == 1
          and NODE_CALLS[0][0].startswith("https://rpc.ankr.com/eth/"), (r, [(u[:26], m) for u, m in NODE_CALLS]))
    for g, field, val, host in (("alchemy", "TJ_ALCHEMY_KEY", "TESTal_00000000000000000000000007", "eth-mainnet.g.alchemy.com"),
                                ("nodereal", "TJ_NODEREAL_KEY", "TESTnr_0000000000000001", "bsc-mainnet.nodereal.io"),
                                ("quicknode", "TJ_QUICKNODE_BSC_KEY", "https://x-y.bsc.quiknode.pro/tok0000000/", "x-y.bsc.quiknode.pro")):
        NODE_CALLS.clear()
        onboarding._node_rpc = node_rpc_err("http4xx", 401)
        r = onboarding._dispatch("keys/save", {"group": g, "values": {field: val}})
        check(f"C4a {g} 키 401 = 저장 안 함 · 그 노드 1콜", r.get("ok") is False and not ss.read_env().get(field) and len(NODE_CALLS) == 1
              and host in NODE_CALLS[0][0], (r, NODE_CALLS))
        NODE_CALLS.clear()
        onboarding._node_rpc = node_rpc_err("timeout")
        r = onboarding._dispatch("keys/save", {"group": g, "values": {field: val}})
        check(f"C4b {g} 시간 초과 = 저장 + 경고", r.get("ok") is True and ss.read_env().get(field) == val and r.get("note"), r)
    cfg_save = open(CP, encoding="utf-8").read()
    try:
        with open(CP, "w", encoding="utf-8") as f9:
            json.dump(dict(CFG, wallets=[{"type": "evm", "chain": "base", "address": W2, "label": "베이스만"}]), f9)
        for code9, ok9 in ((403, True), (401, False)):
            ss.write_env({"TJ_ALCHEMY_KEY": None})
            NODE_CALLS.clear()
            onboarding._node_rpc = node_rpc_err("http4xx", code9)
            r = onboarding._dispatch("keys/save", {"group": "alchemy", "values": {"TJ_ALCHEMY_KEY": "TESTal_00000000000000000000000009"}})
            hit9 = NODE_CALLS and "base-mainnet.g.alchemy.com" in NODE_CALLS[0][0]
            if ok9:
                check("C4f Base 지갑만 = Base 네트워크로 시험 · 403(네트워크 꺼짐) = 저장 + 경고(거부 아님)", hit9 and r.get("ok") is True and r.get("note")
                      and ss.read_env().get("TJ_ALCHEMY_KEY"), (r, [(u[:34], m) for u, m in NODE_CALLS]))
            else:
                check("C4g Alchemy 401(키 없음) = 거부", hit9 and r.get("ok") is False and not ss.read_env().get("TJ_ALCHEMY_KEY"), (r, NODE_CALLS))
    finally:
        with open(CP, "w", encoding="utf-8") as f9:
            f9.write(cfg_save)
    HTTP_CALLS = []

    def http_as(code, body):
        def f(url, headers=None, data=None, method=None, timeout=12, sol=False):
            HTTP_CALLS.append(url.split("?")[0])
            if code is None:
                raise OSError("시험: 연결 실패")
            return code, body
        f._tj_test_mock = True
        return f
    cases = [("helius", {"TJ_HELIUS_KEY": "hel-test-0000"}, (401, {"error": "invalid api key"}), (None, None)),
             ("etherscan", {"TJ_ETHERSCAN_KEY": "ESTEST0000000000000000000000000000"}, (200, {"status": "0", "message": "NOTOK", "result": "Invalid API Key (#err2)|x"}),
              (200, {"status": "0", "message": "NOTOK", "result": "Max calls per sec rate limit reached (3/sec)"})),
             ("opensea", {"TJ_OPENSEA_KEY": "os-test-0000"}, (401, {"detail": "Invalid API key"}), (None, None)),
             ("upbit", {"UPBIT_ACCESS": "upA0000", "UPBIT_SECRET": "upS0000"}, (401, {"error": {"name": "invalid_access_key", "message": "잘못된 키"}}), (None, None)),
             ("bithumb", {"TJ_BITHUMB_KEY": "btA0000", "TJ_BITHUMB_SECRET": "btS0000"}, (401, {"error": {"name": "invalid_access_key", "message": "x"}}), (None, None)),
             ("kucoin", None, (401, {"code": "400003", "msg": "KC-API-KEY not exists"}), (None, None)),
             ("gate", None, (401, {"label": "INVALID_KEY", "message": "Invalid key"}), (None, None))]
    for g, vals, bad, soft in cases:
        if g not in ss.GROUPS:
            check(f"C4c {g} 그룹 있음", False, sorted(ss.GROUPS))
            continue
        fields = [k for k, _ in ss.GROUPS[g]["fields"]]
        vals = vals or {k: f"{g}T{i}000000" for i, k in enumerate(fields)}
        body = {"group": g, "values": vals, "readOnlyAck": True}
        ss.write_env({k: None for k in fields})
        HTTP_CALLS.clear()
        onboarding._http = http_as(*bad)
        onboarding.RL.reset() if hasattr(onboarding.RL, "reset") else None
        r = T.safe(onboarding._dispatch, "keys/save", body)
        env9 = ss.read_env()
        check(f"C4c {g} 확실한 거부 = 저장 안 함 · 1콜 · 키 값 응답에 없음", r.get("ok") is False and not any(env9.get(k) for k in fields) and len(HTTP_CALLS) == 1
              and not any(v in json.dumps(r, ensure_ascii=False) for v in vals.values()), (r, HTTP_CALLS))
        HTTP_CALLS.clear()
        onboarding._http = http_as(*soft)
        r = T.safe(onboarding._dispatch, "keys/save", body)
        env9 = ss.read_env()
        check(f"C4d {g} 연결 실패·일시 오류 = 저장 + 경고", r.get("ok") is True and all(env9.get(k) == vals[k] for k in fields) and r.get("note"), r)
        HTTP_CALLS.clear()
        ok_body = {"helius": (200, {"result": "ok"}), "etherscan": (200, {"status": "1", "result": "1"}), "opensea": (200, {"total": {}}),
                   "upbit": (200, []), "bithumb": (200, []), "kucoin": (200, {"code": "200000", "data": []}), "gate": (200, [])}[g]
        onboarding._http = http_as(*ok_body)
        r = T.safe(onboarding._dispatch, "keys/save", body)
        check(f"C4e {g} 정상 = 저장 · 경고 없음", r.get("ok") is True and not r.get("note"), r)
finally:
    onboarding._node_rpc = real_node_rpc
    onboarding._http = real_http

T.finish()
