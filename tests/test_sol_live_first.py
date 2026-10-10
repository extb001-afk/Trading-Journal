#!/usr/bin/env python3
import contextlib
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as H

os.fsync = lambda fd: None

import common
import bf_engine
import sol_watch
from inbox import SegmentWriter

chk = H.chk
NEW = hasattr(sol_watch, "LIVE_FIRST_HOURS")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TOKEN_PROG = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def b58(tag):
    n = int.from_bytes(hashlib.sha256(("sollive-" + str(tag)).encode()).digest(), "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return s[:44]


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, float(s))


T0 = 1_791_000_000.0
clock = Clock(T0)
time.time = clock.time
time.sleep = clock.sleep
SLOT0 = 300_000_000
MINT = b58("mint")
X = b58("sender")


def slot_of(ts):
    return SLOT0 + int(round((ts - T0) / 0.4))


class Chain:

    def __init__(self):
        self.sigs = {}
        self.txs = {}
        self.fail = set()
        self.atas = {}
        self.calls = []
        self.tx_cost = 0.3
        self.list_cost = 0.2

    def add(self, addrs, sig, ts, tx):
        for a in addrs:
            self.sigs.setdefault(a, []).append((sig, slot_of(ts), int(ts)))
        self.txs[sig] = tx

    def sol_in(self, owner, sig, ts, amt=10 ** 8):
        tx = {"slot": slot_of(ts), "blockTime": int(ts),
              "meta": {"fee": 5000, "err": None, "preBalances": [5 * 10 ** 9, 10 ** 9], "postBalances": [5 * 10 ** 9 - amt - 5000, 10 ** 9 + amt],
                       "preTokenBalances": [], "postTokenBalances": [], "innerInstructions": []},
              "transaction": {"message": {"accountKeys": [{"pubkey": X, "signer": True, "writable": True},
                                                          {"pubkey": owner, "signer": False, "writable": True}],
                                          "instructions": [{"programId": "11111111111111111111111111111111"}]}}}
        self.add([owner], sig, ts, tx)

    def tok_in(self, owner, ata, sig, ts, amt=4_000_000):
        tx = {"slot": slot_of(ts), "blockTime": int(ts),
              "meta": {"fee": 5000, "err": None, "preBalances": [10 ** 9, 2 * 10 ** 6], "postBalances": [10 ** 9 - 5000, 2 * 10 ** 6],
                       "preTokenBalances": [{"accountIndex": 1, "mint": MINT, "owner": owner, "uiTokenAmount": {"amount": "0", "decimals": 6}}],
                       "postTokenBalances": [{"accountIndex": 1, "mint": MINT, "owner": owner, "uiTokenAmount": {"amount": str(amt), "decimals": 6}}],
                       "innerInstructions": []},
              "transaction": {"message": {"accountKeys": [{"pubkey": X, "signer": True, "writable": True},
                                                          {"pubkey": ata, "signer": False, "writable": True}],
                                          "instructions": [{"programId": TOKEN_PROG}]}}}
        self.add([ata], sig, ts, tx)

    def n_tx(self, sig):
        return sum(1 for m, k, _ in self.calls if m == "getTransaction" and k == sig)


class MockRpc:
    rl_last = False
    rl_seen = 0
    primary_open_until = 0
    fallbacks = []
    url = "https://sol-rpc.mock.invalid"
    last_src = "primary"
    last_url = url
    proc = "tj-sol"
    head_url = None
    head_window = 0

    def __init__(self, chain, metered=False):
        self.c = chain
        self.metered = metered
        self.room = 10 ** 6
        self.fill_used = 0
        self._k = ["head"]

    def primary_open(self):
        return False

    def hl_closed(self):
        return False

    def fill_room(self):
        return max(0, self.room - self.fill_used)

    def set_room(self, n):
        self.room, self.fill_used = n, 0

    def kind(self):
        return self._k[-1]

    @contextlib.contextmanager
    def as_kind(self, k):
        self._k.append(k)
        try:
            yield
        finally:
            self._k.pop()

    @contextlib.contextmanager
    def hint(self, **kw):
        yield

    def call(self, method, params, timeout=25):
        c = self.c
        now = clock.time()
        if self.kind() == "fill" and method in ("getSignaturesForAddress", "getTransaction"):
            self.fill_used += 1
        if method == "getSignaturesForAddress":
            a, opt = params
            c.calls.append((method, a, self.kind()))
            clock.sleep(c.list_cost)
            rows = sorted((r for r in c.sigs.get(a, []) if r[2] <= now), key=lambda r: -r[1])
            out, on = [], not opt.get("before")
            for sig, sl, bt in rows:
                if not on:
                    on = sig == opt.get("before")
                    continue
                if sig == opt.get("until"):
                    break
                out.append({"signature": sig, "slot": sl, "blockTime": bt, "err": None})
            return out[: opt.get("limit", 1000)]
        if method == "getTransaction":
            s = params[0]
            c.calls.append((method, s, self.kind()))
            clock.sleep(c.tx_cost)
            if s in c.fail:
                raise RuntimeError("시험: 노드 오류 주입")
            return json.loads(json.dumps(c.txs[s]))
        if method == "getTokenAccountsByOwner":
            o, prog = params[0], params[1]["programId"]
            c.calls.append((method, o, self.kind()))
            return {"value": [{"pubkey": a} for a in (c.atas.get(o, []) if prog == TOKEN_PROG else [])]}
        if method == "getSlot":
            return slot_of(now)
        if method == "getAsset":
            return {"token_info": {"decimals": 6, "symbol": "TKN"}}
        raise RuntimeError("시험 노드: " + method)

    def batch(self, method, params_list, timeout=30):
        return [self.call(method, p) for p in params_list]

    def _call(self, url, method, params, timeout=25):
        return self.call(method, params)


class HelStub:
    fill_first = True
    burst = 0.5
    budget = 25_000

    def fill_cap_fresh(self):
        return 20_000

    def keep_credits(self):
        return 100

    def used(self, now=None):
        return (0, 0)

    def room(self, kind="head", now=None, proc=None):
        return 10 ** 6

    def day_capped(self, now=None):
        return False


class Inbox:
    def __init__(self):
        self.first = {}
        self.lines = {}

    def scan(self):
        d = os.path.join(common.INBOX_DIR, "sol")
        cnt = {}
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else ():
            for line in open(os.path.join(d, f), encoding="utf-8"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                h = r.get("txhash")
                cnt[h] = cnt.get(h, 0) + 1
                self.first.setdefault(h, clock.time())
        self.lines = cnt
        return cnt


def setup(name, owners, cfg_sol=None, chain=None, metered=False, months=5):
    sd = os.path.join(H.TMP, name, "state")
    os.makedirs(sd, exist_ok=True)
    common.rebase_state(sd)
    bf_engine.HELIUS = HelStub() if metered else _HEL0
    sol9 = {"rpc": "https://sol-rpc.mock.invalid", "poll_sec": 60, "stake": False, "ata_every_cycles": 5, "addr_pace_sec": 0}
    sol9.update(cfg_sol or {})
    cfg = {"wallets": [{"type": "sol", "chain": "sol", "address": o} for o in owners], "backfill_months": months, "sol": sol9}
    rpc = MockRpc(chain, metered=metered)
    sol_watch.Rpc = lambda c9, _r=rpc: _r
    return cfg, rpc


_HEL0 = bf_engine.HELIUS


def watcher(cfg, owners):
    return sol_watch.SolWatcher(cfg, owners, SegmentWriter(os.path.join(common.INBOX_DIR, "sol")))


def run(wt, secs, ib, errs, poll=60, each=None):
    end = clock.time() + secs
    durs = []
    while clock.time() < end:
        t0 = clock.time()
        try:
            wt.cycle()
        except Exception as e:
            errs.append(f"{type(e).__name__}: {e}"[:200])
        durs.append(clock.time() - t0)
        ib.scan()
        if each:
            each()
        clock.sleep(max(5.0, poll - (clock.time() - t0)))
    return durs


def cur(wt):
    return wt.cursor


print("— A 새 설치(공개 RPC) · 옛 기록 하나 계속 실패")
clock.t = T0
cA = Chain()
OA, YA = b58("A-owner"), b58("A-ata")
cA.atas[OA] = [YA]
for i in range(300):
    cA.sol_in(OA, b58(f"A-old-{i}"), T0 - 100 * 86400 + i * 25000)
cA.sol_in(OA, "A-dep-new", T0 - 3600)
cA.tok_in(OA, YA, "A-tok-new", T0 - 1800)
cA.fail.add(b58("A-old-10"))
cfg, rpc = setup("A", [OA], chain=cA)
wt = watcher(cfg, [OA])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
got = ib.scan()
chk("A-dep-new" in got and "A-tok-new" in got, "[A] 첫 사이클에 최근 SOL 입금·토큰 입금 방출(옛 기록 하나가 실패 중이어도)",
    {"dep": "A-dep-new" in got, "tok": "A-tok-new" in got, "방출 수": len(got)})
chk(OA not in cur(wt) and "_synced_at" not in cur(wt) and ("_persp:" + OA) in cur(wt),
    "[A] 소유자 첫 백필이 안 끝난 동안 소유자 커서·동기화 도장 없음 · 새 관점 표식 유지(기초잔고 대사 보류 규약 그대로 · 다 받은 토큰 계정만 먼저 확정 가능)",
    {k: v for k, v in cur(wt).items() if not k.startswith("_slot")})
cA.fail.clear()
run(wt, 20 * 60, ib, errs)
got = ib.scan()
allA = {s for rows in cA.sigs.values() for s, _sl, _bt in rows}
dupA = {h: n for h, n in got.items() if n > 1}
chk(allA <= set(got) and OA in cur(wt) and YA in cur(wt) and isinstance(cur(wt).get("_synced_at"), int),
    "[A] 실패가 풀리면 완주 — 전부 방출 · 소유자·토큰 계정 커서 · 동기화 도장", {"빠짐": len(allA - set(got)), "커서": [OA in cur(wt), YA in cur(wt)]})
chk(not dupA, "[A] 같은 서명을 두 번 보내지 않음(실패 전에 보낸 것을 새 관점으로 다시 읽지 않음)", {"중복": len(dupA)})
chk(not [k for k in cur(wt) if k.startswith(("_hl:", "_fbw:"))], "[A] 첫 동기화 끝 = 엿보기 기준·진행 표식 정리",
    [k for k in cur(wt) if k.startswith(("_hl:", "_fbw:"))])

print("— B 새 설치 큰 지갑(옛 기록 2,000건) · 백필 중 새 입금 · 중간 재기동")
clock.t = T0
cB = Chain()
OB = b58("B-owner")
for i in range(2000):
    cB.sol_in(OB, b58(f"B-old-{i}"), T0 - 120 * 86400 + i * 4000)
cB.sol_in(OB, "B-dep-new", T0 - 7200)
cB.sol_in(OB, "B-live-2", T0 + 150)
cB.sol_in(OB, "B-live-3", T0 + 700)
cfg, rpc = setup("B", [OB], chain=cB)
wt = watcher(cfg, [OB])
ib, errs = Inbox(), []
fbw_seen = {}
durs = run(wt, 400, ib, errs, each=lambda: fbw_seen.update({"v": cur(wt).get("_fbw:" + OB)}) if cur(wt).get("_fbw:" + OB) else None)
got = ib.scan()
chk(ib.first.get("B-dep-new", 1e18) - T0 <= durs[0] + 1, "[B] 첫 사이클에 최근 입금 방출", {"초": round(ib.first.get("B-dep-new", 1e18) - T0, 1)})
chk(durs and durs[0] <= 200, "[B] 첫 사이클이 옛 기록 전부를 붙잡지 않음(≤ 200초 — 옛 구간 시간 상한)", {"첫 사이클 초": round(durs[0], 1) if durs else None})
lat2 = ib.first.get("B-live-2", 1e18) - (T0 + 150)
chk(lat2 <= 240, "[B] 백필 중에 들어온 새 입금이 4분 안에 방출(실시간 확인이 계속 돎)", {"초": round(lat2, 1)})
chk(OB not in cur(wt) and (not NEW or isinstance(fbw_seen.get("v"), dict)),
    "[B] 아직 백필 중(커서 없음) · 진행 표식 `_fbw:` 기록(재기동 대비)", {"커서": OB in cur(wt), "fbw": fbw_seen.get("v")})
wt = watcher(cfg, [OB])
run(wt, 90 * 60, ib, errs)
got = ib.scan()
allB = {s for s, _sl, _bt in cB.sigs[OB]}
lat3 = ib.first.get("B-live-3", 1e18) - (T0 + 700)
chk(allB <= set(got) and OB in cur(wt), "[B] 재기동 뒤 완주 — 전부 방출 · 커서", {"빠짐": len(allB - set(got)), "커서": OB in cur(wt)})
chk(lat3 <= 240, "[B] 재기동 뒤 백필 중 새 입금도 4분 안", {"초": round(lat3, 1)})
n_old2 = sum(1 for i in range(2000) if cB.n_tx(b58(f"B-old-{i}")) > 1)
n_tx = sum(1 for m, _k, _ in cB.calls if m == "getTransaction")
chk(n_old2 == 0 and n_tx <= len(allB), "[B] 끊어 받아도·재기동해도 같은 서명 다시 읽기 없음(진행 표식 = 슬롯 하한 + 그 위에서 보낸 최근 서명)",
    {"두 번 읽은 옛 서명": n_old2, "상세 호출": n_tx, "서명": len(allB)})
chk(not errs, "[B] 사이클 예외 없음", errs[:3])

print("— C 헬리우스 · 옛 기록 몫 0(차례 대기) → 최근 입금은 실시간 몫으로")
clock.t = T0
cC = Chain()
OC = b58("C-owner")
for i in range(300):
    cC.sol_in(OC, b58(f"C-old-{i}"), T0 - 90 * 86400 + i * 20000)
cC.sol_in(OC, "C-dep-new", T0 - 7200)
cfg, rpc = setup("C", [OC], chain=cC, metered=True)
rpc.set_room(0)
wt = watcher(cfg, [OC])
ib, errs = Inbox(), []
run(wt, 10 * 60, ib, errs)
got = ib.scan()
kinds = {(m, k): kd for m, k, kd in cC.calls}
chk("C-dep-new" in got and ib.first["C-dep-new"] - T0 <= 70, "[C] 옛 기록 몫이 없어도 첫 사이클에 최근 입금 방출", {"방출": sorted(got)[:5]})
chk(kinds.get(("getTransaction", "C-dep-new")) == "head" and not any(kd == "fill" for _m, _k, kd in cC.calls),
    "[C] 최근 구간 = 실시간 몫(head) · 옛 기록 몫 0 동안 옛 기록(fill) 호출 0", {"dep 종류": kinds.get(("getTransaction", "C-dep-new")),
                                                                    "fill 호출": sum(1 for _m, _k, kd in cC.calls if kd == "fill")})
chk(OC not in cur(wt) and "_synced_at" not in cur(wt), "[C] 차례 대기 중 커서·도장 없음")
rpc.set_room(10_000)
run(wt, 30 * 60, ib, errs)
got = ib.scan()
allC = {s for s, _sl, _bt in cC.sigs[OC]}
chk(allC <= set(got) and OC in cur(wt), "[C] 몫이 나면 나머지 완주", {"빠짐": len(allC - set(got))})
chk(cC.n_tx("C-dep-new") == 1 and not {h for h, n in got.items() if n > 1}, "[C] 먼저 받은 최근 입금을 다시 읽거나 두 번 보내지 않음",
    {"dep 상세 호출": cC.n_tx("C-dep-new")})
chk(any(kd == "fill" for m, _k, kd in cC.calls if m == "getTransaction"), "[C] 옛 구간 상세 = 옛 기록 몫(fill) 그대로")

print("— D #15 헬리우스 · 첫 백필 중 1건 실패 뒤 몫 판정 = 안 보낸 건수")
clock.t = T0
cD = Chain()
cD.tx_cost = 0.01
OD = b58("D-owner")
for i in range(1000):
    cD.sol_in(OD, b58(f"D-old-{i}"), T0 - 60 * 86400 + i * 4000)
cfg, rpc = setup("D", [OD], chain=cD, metered=True, cfg_sol={"old_slice_sec": 0})
rpc.set_room(1200)
cD.fail.add(b58("D-old-600"))
wt = watcher(cfg, [OD])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
got = ib.scan()
sent1 = sum(1 for i in range(1000) if b58(f"D-old-{i}") in got)
cD.fail.clear()
rpc.set_room(500)
run(wt, 10 * 60, ib, errs)
got = ib.scan()
chk(sent1 == 600 and OD in cur(wt) and len(got) == 1000, "[D] 남은 401건이 오늘 몫(500) 안이라 같은 날 이어서 완주(종전 = 1,000건으로 세어 다음 날까지 대기)",
    {"첫 사이클 방출": sent1, "커서": OD in cur(wt), "방출": len(got)})
chk(sum(1 for i in range(600) if cD.n_tx(b58(f"D-old-{i}")) > 1) == 0, "[D] 이미 보낸 600건을 다시 읽지 않음")

print("— E 기존 설치 재시작(5일 멈춤) · 밀린 옛 서명 하나 실패")
clock.t = T0
cE = Chain()
OE, OU = b58("E-owner"), b58("E-other")
cE.sol_in(OE, "E-base", T0 - 5 * 86400 - 600)
cE.sol_in(OU, "U-base", T0 - 5 * 86400 - 600)
for i in range(300):
    cE.sol_in(OE, b58(f"E-gap-{i}"), T0 - 5 * 86400 + i * 1416)
cE.sol_in(OU, "U-new", T0 - 3600)
fail_e = b58("E-gap-50")
cE.fail.add(fail_e)
sd = os.path.join(H.TMP, "E", "state")
os.makedirs(sd, exist_ok=True)
pre_cur = {OE: "E-base", "_slot:" + OE: slot_of(T0 - 5 * 86400 - 600), OU: "U-base", "_slot:" + OU: slot_of(T0 - 5 * 86400 - 600),
           "_cov_ts:" + OE: int(T0 - 150 * 86400), "_cov_ts:" + OU: int(T0 - 150 * 86400), "_synced_at": int(T0 - 5 * 86400)}
common.atomic_write_json(os.path.join(sd, "cursor_sol.json"), pre_cur)
cfg, rpc = setup("E", [OE, OU], chain=cE)
wt = watcher(cfg, [OE, OU])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
got = ib.scan()
newest_e = b58("E-gap-299")
chk(newest_e in got and "U-new" in got, "[E] 첫 사이클에 최근(24시간 안) 서명 방출 — 밀린 옛 서명 실패와 무관", {"E 최신": newest_e in got, "U": "U-new" in got})
chk(cur(wt).get(OU) == "U-new" and cur(wt).get(OE) == "E-base", "[E] 다 처리한 지갑(U) 커서는 전진 · 실패가 남은 지갑(E) 커서는 그대로",
    {"U": cur(wt).get(OU), "E": cur(wt).get(OE)})
cE.fail.clear()
run(wt, 15 * 60, ib, errs)
got = ib.scan()
allE = {s for rows in cE.sigs.values() for s, _sl, bt in rows if bt >= T0 - 5 * 86400}
chk(allE <= set(got) and cur(wt).get(OE) == newest_e and not {h for h, n in got.items() if n > 1},
    "[E] 풀리면 밀린 것 전부 한 번씩 · 커서 = 최신", {"빠짐": len(allE - set(got)), "E 커서": cur(wt).get(OE)})

print("— F 평소(기존 설치) = 종전과 같음 · 끔 = 종전 순서")
clock.t = T0
cF = Chain()
O1, O2 = b58("F-1"), b58("F-2")
for o in (O1, O2):
    cF.sol_in(o, "base-" + o[:6], T0 - 86400)
cF.sol_in(O1, "F-a", T0 - 300)
cF.sol_in(O2, "F-b", T0 - 200)
cF.sol_in(O1, "F-c", T0 - 100)
sd = os.path.join(H.TMP, "F", "state")
os.makedirs(sd, exist_ok=True)
common.atomic_write_json(os.path.join(sd, "cursor_sol.json"), {O1: "base-" + O1[:6], O2: "base-" + O2[:6], "_cov_ts:" + O1: int(T0 - 150 * 86400),
                                                                "_cov_ts:" + O2: int(T0 - 150 * 86400)})
cfg, rpc = setup("F", [O1, O2], chain=cF)
wt = watcher(cfg, [O1, O2])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
order = [h for h, _t in sorted(ib.first.items(), key=lambda kv: kv[1])]
recs = []
d9 = os.path.join(common.INBOX_DIR, "sol")
for f in sorted(os.listdir(d9)):
    recs += [json.loads(x)["txhash"] for x in open(os.path.join(d9, f), encoding="utf-8") if x.strip()]
chk(recs == ["F-a", "F-b", "F-c"] and cur(wt).get(O1) == "F-c" and cur(wt).get(O2) == "F-b" and isinstance(cur(wt).get("_synced_at"), int),
    "[F] 새 서명 몇 건 = 오래된 것부터 · 커서 전진 · 동기화 도장(종전 그대로)", {"순서": recs, "커서": [cur(wt).get(O1), cur(wt).get(O2)]})
clock.t = T0
cF2 = Chain()
O3 = b58("F-3")
for i in range(20):
    cF2.sol_in(O3, b58(f"F2-old-{i}"), T0 - 30 * 86400 + i * 1000)
cF2.sol_in(O3, "F2-new", T0 - 600)
cfg, rpc = setup("F2", [O3], chain=cF2, cfg_sol={"live_first_hours": 0})
wt = watcher(cfg, [O3])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
recs = []
d9 = os.path.join(common.INBOX_DIR, "sol")
for f in sorted(os.listdir(d9)):
    recs += [json.loads(x)["txhash"] for x in open(os.path.join(d9, f), encoding="utf-8") if x.strip()]
chk(len(recs) == 21 and recs[-1] == "F2-new", "[F] live_first_hours 0 = 종전 순서(오래된 것부터 · 최신이 끝)", {"끝": recs[-1:] if recs else None})

print("— G 기존 지갑의 새 토큰 계정(이력 2,500건 · 스풀 중)")
clock.t = T0
cG = Chain()
OG, ZG = b58("G-owner"), b58("G-ata")
cG.atas[OG] = [ZG]
cG.sol_in(OG, "G-base", T0 - 86400)
for i in range(2499):
    cG.tok_in(OG, ZG, b58(f"G-old-{i}"), T0 - 100 * 86400 + i * 3000)
cG.tok_in(OG, ZG, "G-tok-new", T0 - 1200)
sd = os.path.join(H.TMP, "G", "state")
os.makedirs(sd, exist_ok=True)
common.atomic_write_json(os.path.join(sd, "cursor_sol.json"), {OG: "G-base", "_cov_ts:" + OG: int(T0 - 150 * 86400)})
cfg, rpc = setup("G", [OG], chain=cG, cfg_sol={"sig_spool_pages": 1})
wt = watcher(cfg, [OG])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
got = ib.scan()
chk("G-tok-new" in got and ("_sigbf:" + ZG) in cur(wt), "[G] 스풀이 끝나기 전 첫 사이클에 최근 토큰 입금 방출", {"tok": "G-tok-new" in got,
                                                                                         "스풀 중": ("_sigbf:" + ZG) in cur(wt)})
doneG = {}
run(wt, 90 * 60, ib, errs, each=lambda: doneG.setdefault("t", clock.time()) if ZG in cur(wt) else None)
got = ib.scan()
allG = {s for s, _sl, _bt in cG.sigs[ZG]}
chk(doneG.get("t", 1e18) - T0 <= 45 * 60, "[G] 끊어 받는 토큰 계정 첫 백필도 소유자 사이클마다 이어 받음(2,500건 ≤ 45분 · 상세만 ≈ 23분 — 전체 사이클(5번에 1번)만 기다리면 ≈ 2시간)",
    {"분": round((doneG.get("t", 1e18) - T0) / 60, 1)})
chk(allG <= set(got) and ZG in cur(wt) and cG.n_tx("G-tok-new") == 1 and not {h for h, n in got.items() if n > 1},
    "[G] 스풀 끝 → 옛 이력 완주 · 최근 입금 다시 읽기·중복 없음", {"빠짐": len(allG - set(got)), "커서": ZG in cur(wt), "tok 상세": cG.n_tx("G-tok-new")})

print("— H 새로 찾은 스테이크 계정 첫 백필(1,500건 · 끊어 받기) — 같은 서명을 사이클마다 다시 읽는 고리 없음")
clock.t = T0
cH = Chain()
OH, KH = b58("H-owner"), b58("H-stake")
cH.sol_in(OH, "H-base", T0 - 86400)
for i in range(1500):
    cH.sol_in(KH, b58(f"H-stk-{i}"), T0 - 100 * 86400 + i * 5000)
sd = os.path.join(H.TMP, "H", "state")
os.makedirs(sd, exist_ok=True)
common.atomic_write_json(os.path.join(sd, "cursor_sol.json"), {OH: "H-base", "_cov_ts:" + OH: int(T0 - 150 * 86400),
                                                                "_stk:" + KH: {"w": OH, "t0": int(T0 - 150 * 86400), "rwd_next": 0, "first": None}})
cfg, rpc = setup("H", [OH], chain=cH)
wt = watcher(cfg, [OH])
ib, errs = Inbox(), []
run(wt, 60 * 60, ib, errs)
got = ib.scan()
allH = {s for s, _sl, _bt in cH.sigs[KH]}
twice = sum(1 for s in allH if cH.n_tx(s) > 1)
chk(allH <= set(got) and KH in cur(wt) and twice == 0, "[H] 스테이크 계정 첫 백필 완주 · 끊어 받아도 다시 읽기 0",
    {"빠짐": len(allH - set(got)), "커서": KH in cur(wt), "두 번 읽음": twice})

print("— I 헬리우스 · 하루 몫보다 큰 첫 백필(1,500건 · 남은 몫 500) — 남은 몫만큼 진행하고 멈춤 → 새 날 이어서")
clock.t = T0
cI = Chain()
OI = b58("I-owner")
for i in range(1500):
    cI.sol_in(OI, b58(f"I-old-{i}"), T0 - 100 * 86400 + i * 5000)
cI.sol_in(OI, "I-dep-new", T0 - 600)
cfg, rpc = setup("I", [OI], chain=cI, metered=True)
rpc.set_room(500)
wt = watcher(cfg, [OI])
ib, errs = Inbox(), []
run(wt, 30 * 60, ib, errs)
got = ib.scan()
fill_tx = sum(1 for m, _k, kd in cI.calls if m == "getTransaction" and kd == "fill")
sent_old = sum(1 for i in range(1500) if b58(f"I-old-{i}") in got)
chk("I-dep-new" in got and 300 <= sent_old and rpc.fill_used <= 500 + 1 and OI not in cur(wt),
    "[I] 오늘 남은 옛 기록 몫(500)만큼 옛 기록 진행 · 몫을 넘지 않음 · 최근 입금은 첫 사이클(종전 = 하루 몫보다 큰 주소는 그날 상세 0)",
    {"옛 방출": sent_old, "fill 호출": rpc.fill_used, "fill 상세": fill_tx, "최근": "I-dep-new" in got})
rpc.set_room(5000)
run(wt, 60 * 60, ib, errs)
got = ib.scan()
allI = {s for s, _sl, _bt in cI.sigs[OI]}
chk(allI <= set(got) and OI in cur(wt) and sum(1 for s in allI if cI.n_tx(s) > 1) == 0 and not {h for h, n in got.items() if n > 1},
    "[I] 새 날 몫으로 이어서 완주 · 다시 읽기·중복 0", {"빠짐": len(allI - set(got)), "커서": OI in cur(wt)})

print("— J 프로세스 안에서 소유자가 늘어남(운영은 재시작) — 이미 보낸 서명도 새 소유자 관점으로 다시(레그 빠짐 0)")
clock.t = T0
cJ = Chain()
PJ, NJ = b58("J-p"), b58("J-n")
cJ.sol_in(PJ, "J-base", T0 - 86400)
txj = {"slot": slot_of(T0 - 600), "blockTime": int(T0 - 600),
       "meta": {"fee": 5000, "err": None, "preBalances": [5 * 10 ** 9, 10 ** 9], "postBalances": [4 * 10 ** 9 - 5000, 2 * 10 ** 9],
                "preTokenBalances": [], "postTokenBalances": [], "innerInstructions": []},
       "transaction": {"message": {"accountKeys": [{"pubkey": PJ, "signer": True, "writable": True}, {"pubkey": NJ, "signer": False, "writable": True}],
                                   "instructions": [{"programId": "11111111111111111111111111111111"}]}}}
cJ.add([PJ, NJ], "J-pn", T0 - 600, txj)
sd = os.path.join(H.TMP, "J", "state")
os.makedirs(sd, exist_ok=True)
common.atomic_write_json(os.path.join(sd, "cursor_sol.json"), {PJ: "J-base", "_cov_ts:" + PJ: int(T0 - 150 * 86400)})
cfg, rpc = setup("J", [PJ], chain=cJ)
wt = watcher(cfg, [PJ])
ib, errs = Inbox(), []
run(wt, 1, ib, errs)
wt.owners.append(NJ)
run(wt, 10 * 60, ib, errs)
recsJ = []
d9 = os.path.join(common.INBOX_DIR, "sol")
for f in sorted(os.listdir(d9)):
    recsJ += [json.loads(x) for x in open(os.path.join(d9, f), encoding="utf-8") if x.strip()]
rp = [r for r in recsJ if r.get("txhash") == "J-pn" and r.get("repersp")]
chk(rp and any(d.get("owner") == NJ for d in rp[-1].get("deltas") or []) and NJ in cur(wt),
    "[J] 새 소유자 첫 백필이 이미 보낸 서명을 새 관점으로 다시 보냄(받은 쪽 레그 포함)", {"repersp": len(rp), "커서": NJ in cur(wt)})

print("— K 끊어 받던 새 토큰 계정(800건 · 스풀 아님)이 중간에 닫힘 — 남은 이력 빠짐 0 · 그동안 동기화 도장 없음")
clock.t = T0
cK = Chain()
OK_, YK = b58("K-owner"), b58("K-ata")
cK.atas[OK_] = [YK]
for i in range(5):
    cK.sol_in(OK_, b58(f"K-o-{i}"), T0 - 50 * 86400 + i * 86400)
for i in range(800):
    cK.tok_in(OK_, YK, b58(f"K-y-{i}"), T0 - 100 * 86400 + i * 9000)
cfg, rpc = setup("K", [OK_], chain=cK)
wt = watcher(cfg, [OK_])
ib, errs = Inbox(), []
allK = {s for s, _sl, _bt in cK.sigs[YK]}
bad_stamp = []


def _k_each():
    c9 = cur(wt)
    if isinstance(c9.get("_synced_at"), int) and clock.time() - c9["_synced_at"] < 600 and not allK <= set(ib.lines):
        bad_stamp.append(round(clock.time() - T0))


run(wt, 1, ib, errs, each=_k_each)
part_k = sum(1 for s in allK if s in ib.lines)
cK.atas[OK_] = []
run(wt, 90 * 60, ib, errs, each=_k_each)
got = ib.scan()
chk(0 < part_k < 800 and allK <= set(got) and YK not in cur(wt) and ("_fb_wait:" + YK) not in cur(wt) and not bad_stamp,
    "[K] 닫힌 뒤에도 남은 이력 전부 받고 퇴역 · 다 받기 전 동기화 도장 0(코덱스 so494)",
    {"첫 사이클": part_k, "빠짐": len(allK - set(got)), "커서": YK in cur(wt), "대기 표식": ("_fb_wait:" + YK) in cur(wt), "도장 위반 초": bad_stamp[:3]})

print("— L 최근 구간 끔(live_first_hours 0) · 헬리우스 · 남은 옛 기록 몫 500 < 첫 백필 1,000 → 종전처럼 차례 대기")
clock.t = T0
cL = Chain()
OL = b58("L-owner")
for i in range(1000):
    cL.sol_in(OL, b58(f"L-old-{i}"), T0 - 60 * 86400 + i * 4000)
cfg, rpc = setup("L", [OL], chain=cL, metered=True, cfg_sol={"live_first_hours": 0})
rpc.set_room(500)
wt = watcher(cfg, [OL])
ib, errs = Inbox(), []
run(wt, 10 * 60, ib, errs)
fill_txL = sum(1 for m, _k, kd in cL.calls if m == "getTransaction" and kd == "fill")
chk(fill_txL == 0 and OL not in cur(wt), "[L] 끈 모드 = 종전 몫 판정(첫 백필 건수 = 안 보낸 전부 · 몫 우회 0 · 코덱스 so494)", {"fill 상세": fill_txL})

print("— M 새 설치 · 토큰 계정 20개 × 최근 100건(최근 구간만 2,000건) — 최근 구간도 시간 상한 · 주소별 최신 먼저 · 실시간 확인 계속")
clock.t = T0
cM = Chain()
OM = b58("M-owner")
YMs = [b58(f"M-ata-{j}") for j in range(20)]
cM.atas[OM] = list(YMs)
cM.sol_in(OM, "M-o-base", T0 - 30 * 86400)
for j, y in enumerate(YMs):
    for i in range(100):
        cM.tok_in(OM, y, f"M-{j}-{i}", T0 - 20 * 3600 + i * 600 + j)
cM.sol_in(OM, "M-live", T0 + 150)
cfg, rpc = setup("M", [OM], chain=cM)
wt = watcher(cfg, [OM])
auditM = []
wt._pn_audit = lambda: auditM.append(clock.time())
ib, errs = Inbox(), []
durM = run(wt, 400, ib, errs)
got = ib.scan()
tops = [f"M-{j}-99" for j in range(20)]
latM = ib.first.get("M-live", 1e18) - (T0 + 150)
chk(durM and durM[0] <= 200 and all(t in got and ib.first[t] - T0 <= durM[0] + 1 for t in tops),
    "[M] 첫 사이클 ≤ 200초 · 그 안에 토큰 계정마다 가장 새 입금 먼저(코덱스 so494)", {"첫 사이클 초": round(durM[0], 1) if durM else None,
                                                                                "최신 방출": sum(1 for t in tops if t in got)})
chk(latM <= 240, "[M] 최근 구간이 많아도 그동안 들어온 새 입금 4분 안", {"초": round(latM, 1)})
chk(durM and not [t for t in auditM if t <= T0 + durM[0] + 1], "[M] 끊어 받은 전체 사이클엔 publicnode 대조 안 함(안 보낸 서명 = 누락 오판 → 6시간 끊김 방지)",
    {"대조 시각(초)": [round(t - T0) for t in auditM[:3]]})
run(wt, 60 * 60, ib, errs)
got = ib.scan()
allM = {s for rows in cM.sigs.values() for s, _sl, _bt in rows}
chk(allM <= set(got) and all(y in cur(wt) for y in YMs) and not {h for h, n in got.items() if n > 1}
    and sum(1 for s in allM if cM.n_tx(s) > 1) == 0, "[M] 나머지 완주 · 중복·다시 읽기 0", {"빠짐": len(allM - set(got))})

H.finish()
