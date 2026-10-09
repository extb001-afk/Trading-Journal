#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import threading

json.dump({"chains": {}, "wallets": []}, open(os.path.join(os.environ["TJ_BASE"], "config.json"), "w"))
import common
import lpchain
import web

chk = T.chk
MGR = "0x" + "11" * 20
os.makedirs(os.path.join(common.STATE_DIR, "seed_local"), exist_ok=True)
json.dump({"base": {MGR: {"proto": "uni_v4", "name": "Uniswap V4", "stateview": "0x" + "66" * 20}}},
          open(os.path.join(common.STATE_DIR, "seed_local", "lp_managers.json"), "w"))
OWNER = "0x" + "22" * 20
LOC = lambda tid: f"lp:base:{MGR}:{tid}"
TGT = lambda tid, ch="base": (ch, MGR, tid, f"lp:{ch}:{MGR}:{tid}", {"proto": "uni_v4"})

CLOCK = [1_000_000.0]
_real_time = web.time.time
web.time.time = lambda: CLOCK[0]


class Stop(BaseException):
    pass


HOOKS = []
STOP_AT = [None]


def fake_sleep(s):
    CLOCK[0] += float(s)
    for h in list(HOOKS):
        if CLOCK[0] >= h[0]:
            HOOKS.remove(h)
            h[1]()
    if STOP_AT[0] is not None and CLOCK[0] >= STOP_AT[0]:
        raise Stop()


web.time.sleep = fake_sleep

READS = []
LISTS = []
FAIL_IDS = set()


def fake_read(cfg, ch, mgr, tid):
    READS.append((CLOCK[0], tid))
    if tid in FAIL_IDS:
        return {}
    return {"proto": "uni_v4", "liquidity": "1000", "token0": "0x" + "33" * 20, "token1": "0x" + "44" * 20,
            "sym0": "USDC", "sym1": "TKN", "amount0": 100.0, "amount1": 0.0, "fees0": 0.0, "fees1": 0.0,
            "price": 1.0, "inRange": False, "feesOk": True}


def fake_list(cfg, ch, w):
    LISTS.append((CLOCK[0], ch, w))
    return []


fake_read._tj_test_mock = True
fake_list._tj_test_mock = True
lpchain.read_position = fake_read
lpchain.read_stake_reward = lambda *a, **k: {}
lpchain.owner_of = lambda *a, **k: OWNER
lpchain.list_wallet_positions = fake_list


def mk(cfg=None):
    b = web.StateBuilder.__new__(web.StateBuilder)
    b.cfg = cfg or {"wallets": [{"type": "evm", "chain": "base", "address": "0x" + "55" * 20}]}
    b.lock = threading.Lock()
    b._lp_lock = threading.Lock()
    b._lp_targets = [TGT(1)]
    b._refreshing = False
    b.soft_invalidate = lambda kick=True: None
    return b


def reset():
    READS.clear(); LISTS.clear(); HOOKS.clear(); FAIL_IDS.clear()
    STOP_AT[0] = None
    try:
        os.remove(web.LP_POS_PATH)
    except FileNotFoundError:
        pass


def lp_file():
    return common.read_json(web.LP_POS_PATH, {}) or {}


def run_worker(b, until):
    STOP_AT[0] = until
    try:
        b._lp_worker()
    except Stop:
        pass


reset()
b = mk()
t0 = CLOCK[0]
appear = [None]


def add_new():
    appear[0] = CLOCK[0]
    with b._lp_lock:
        b._lp_targets = [TGT(1), TGT(2)]


HOOKS.append((t0 + 21, add_new))
run_worker(b, t0 + 20 + getattr(web, "LP_OPEN_SEC", 300) - 5)
first2 = next((t for t, tid in READS if tid == 2), None)
chk(first2 is not None and appear[0] is not None and first2 - appear[0] <= 30,
    "[1] 정규 주기 직후 생긴 새 포지션이 다음 정규 주기(LP_OPEN_SEC) 전에 30초 안에 평가됨",
    {"appear": appear[0] and appear[0] - t0, "read": first2 and first2 - t0})
chk(LOC(2) in (lp_file().get("positions") or {}), "[1b] 새 포지션 평가가 lp_positions.json 에 들어감")

lists_full = [x for x in LISTS if x[0] <= t0 + 21]
lists_fast = [x for x in LISTS if x[0] > t0 + 21]
chk(len(lists_full) == 1 and not lists_fast, "[2] 지갑 NFT 목록 조회는 정규 주기에서만(빠른 경로 0회)", {"lists": len(LISTS)})
reads1 = [x for x in READS if x[1] == 1]
chk(len(reads1) == 1, "[2b] 이미 평가된 포지션은 빠른 경로에서 다시 읽지 않음", {"reads1": len(reads1)})

reset()
b = mk()
b._lp_refresh_once()
f0 = lp_file()
with b._lp_lock:
    b._lp_targets = [TGT(1), TGT(3)]
CLOCK[0] += 30
r = b._lp_refresh_new() if hasattr(b, "_lp_refresh_new") else None
f1 = lp_file()
chk(r == (1, 1), "[3] 빠른 경로 반환 = (성공 1, 시도 1)", {"r": r})
chk(f1.get("updated") == f0.get("updated") and f1.get("wallet_nfts") == f0.get("wallet_nfts") and f1.get("targets") == f0.get("targets"),
    "[3b] wallet_nfts·targets·updated 는 정규 주기 값 그대로")
chk((f1.get("positions") or {}).get(LOC(1)) == (f0.get("positions") or {}).get(LOC(1)) and LOC(3) in (f1.get("positions") or {}),
    "[3c] 기존 평가 그대로 + 새 포지션만 추가")
chk(((f1.get("positions") or {}).get(LOC(3)) or {}).get("owner") == OWNER, "[3d] 새 포지션도 owner(지갑별 대조용) 기록")

READS.clear()
st0 = os.stat(web.LP_POS_PATH).st_mtime_ns
writes = []
_aw = common.atomic_write_json
common.atomic_write_json = lambda p, o: (writes.append(p), _aw(p, o))
CLOCK[0] += 30
r = b._lp_refresh_new() if hasattr(b, "_lp_refresh_new") else None
common.atomic_write_json = _aw
chk(r == (0, 0) and not READS and not writes and os.stat(web.LP_POS_PATH).st_mtime_ns == st0,
    "[4] 새 대상이 없으면 온체인 읽기 0 · 파일 쓰기 0", {"r": r, "reads": len(READS), "writes": len(writes)})

FAIL_IDS.add(4)
with b._lp_lock:
    b._lp_targets = [TGT(1), TGT(3), TGT(4)]
for _i in range(5):
    CLOCK[0] += 20
    b._lp_refresh_new() if hasattr(b, "_lp_refresh_new") else None
n4 = sum(1 for _t, tid in READS if tid == 4)
chk(n4 == 1, "[5] 읽기 실패 포지션 = 빠른 경로 1회만(정규 주기가 재시도)", {"reads4": n4})
chk(LOC(4) not in (lp_file().get("positions") or {}), "[5b] 실패는 기록하지 않음(평가 대기 유지 — 가짜 0 금지)")
b._lp_refresh_once()
chk(sum(1 for _t, tid in READS if tid == 4) == 2, "[5c] 정규 주기는 실패 포지션을 다시 시도(종전 그대로)")

reset()
b = mk({"wallets": [], "_disabled_chains": ["base"]})
b._lp_targets = []
b._lp_refresh_once()
with b._lp_lock:
    b._lp_targets = [TGT(5)]
CLOCK[0] += 30
r = b._lp_refresh_new() if hasattr(b, "_lp_refresh_new") else None
chk(r == (0, 0) and not [x for x in READS if x[1] == 5], "[6] 꺼 둔 체인의 새 포지션은 빠른 경로도 조회 안 함", {"r": r})

web.time.time = _real_time
T.finish()
