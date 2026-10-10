#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

import common
import bf_engine as B
import nodekeys as NK


def check(n, c, d=""):
    T.chk(bool(c), n, None if c else str(d)[:900])


DAY = int(time.time() // 86400)


def hl_reset(days: dict, cfg: dict):
    d = os.path.join(common.quota_dir(), "helius_budget")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    common.atomic_write_json(os.path.join(d, "head_days.hist"),
                             {"days": {str(DAY - k): {f"seed.{k}.aa": [0, int(v)]} for k, v in days.items()}, "since": DAY - 40})
    B.HELIUS = B.DayMeter("helius_budget", B.helius_day_budget(cfg), fill_first=True)
    B.helius_configure(cfg)
    return d


def ledger_n(d):
    n = 0
    for f in os.listdir(d):
        if f.endswith(".json"):
            j = json.load(open(os.path.join(d, f)))
            if j.get("day") == DAY:
                n += int(j.get("n") or 0)
    return n


N = B.helius_day_budget({})
d1 = hl_reset({1: 240000, 2: 240000, 3: 240000, 4: 70000}, {"sol": {"helius_burst": False}})
ok1 = B.HELIUS.take("y1", 20000, kind="must")
check("Y1a 버스트 꺼도 31일 창: 지난 79만 + 오늘 2만 = 81만 > 80만 → 거절(종전 = 하루 예산 25,806 만 봐서 승인)", ok1 is False, (ok1, ledger_n(d1)))
check("Y1b 그래도 창 안(1만 이하)은 승인", B.HELIUS.take("y1", 5000, kind="must") is True)
check("Y1c 끈 뒤에도 날짜별 기록 31일 보관(3일로 줄면 지난 버스트를 잊음)", B.HELIUS.hist_keep >= 31, B.HELIUS.hist_keep)
fx = B.helius_flex({"sol": {"helius_burst": False}})
check("Y1d helius_flex(끔) = 창은 남기고 배수 1(버스트 없음)", isinstance(fx, dict) and fx.get("x") == 1.0 and fx.get("cap") == 800000, fx)

import sol_watch as SW

os.environ["TJ_HELIUS_KEY"] = "TESThelius0000000000001"
SENT = []


class _FakeResp:
    def __init__(self, b):
        self.b = b

    def read(self, n=-1):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_sol_open(req, timeout, *a, **k):
    SENT.append(req.full_url)
    return _FakeResp(b'{"jsonrpc": "2.0", "id": 1, "result": 123}')


B.sol_open = _fake_sol_open
d2 = hl_reset({1: 800000}, {"sol": {"rpc": "helius"}})
rpc = SW.Rpc({"sol": {"rpc": "helius"}})
check("Y2a 시험 준비: 헬리우스 주 RPC = 계량", rpc.metered is True and "helius-rpc.com" in rpc.url)
net0, n0 = len(SENT), ledger_n(d2)
err2 = None
try:
    rpc._call(rpc.url, "getTransaction", ["sigY2", {"maxSupportedTransactionVersion": 0}])
except Exception as e:
    err2 = e
check("Y2b 창 다 쓴 날 실시간 호출 = 보내기 전 거절(RuntimeError · HTTP 0 · 장부 무변 — 호출측은 다른 노드로)",
      isinstance(err2, RuntimeError) and not isinstance(err2, SW.RateLimited) and "헬리우스" in str(err2)
      and len(SENT) == net0 and ledger_n(d2) == n0, (repr(err2)[:200], len(SENT) - net0, ledger_n(d2) - n0))
err3 = None
with rpc.as_kind("fill"):
    try:
        rpc._call(rpc.url, "getSignaturesForAddress", ["AddrY2"])
    except Exception as e:
        err3 = e
check("Y2c 옛 기록(fill) 호출도 같은 창 거절", isinstance(err3, RuntimeError) and "헬리우스" in str(err3) and len(SENT) == net0 and ledger_n(d2) == n0,
      (repr(err3)[:200], ledger_n(d2) - n0))
d2b = hl_reset({}, {"sol": {"rpc": "helius"}})
net1 = len(SENT)
r2d = rpc._call(rpc.url, "getSlot", [])
check("Y2d 창 넉넉 = 예약 1 크레딧 기록 뒤 전송(가짜 응답)", r2d == 123 and ledger_n(d2b) == 1 and len(SENT) == net1 + 1, (r2d, ledger_n(d2b), len(SENT) - net1))

d3 = hl_reset({1: 1590000}, {"sol": {"helius_monthly_credits": 2_000_000}})
check("Y3a 헬리우스 유료: 지난 159만 + 오늘 2만 > 160만 → 거절(버스트 없음 · 창은 셈)", B.HELIUS.take("y3", 20000, kind="must") is False)
check("Y3b 헬리우스 유료 = 버스트 배수 1", (B.helius_flex({"sol": {"helius_monthly_credits": 2_000_000}}) or {}).get("x") == 1.0)
sp = NK.budget_spec("ankr", {"plan": "paid", "share": 80, "month": None})
dn = os.path.join(common.quota_dir(), "rpc_day_node_y3")
os.makedirs(dn, exist_ok=True)
cap3 = int(sp["month"] * sp["pct"] / 100)
common.atomic_write_json(os.path.join(dn, "head_days.hist"), {"days": {str(DAY - 1): {"x.1.aa": [0, cap3 - 1000]}}, "since": DAY - 40})
B.rpc_day_configure({"rpc_day_limits": {"node_y3": dict(sp, hosts=["*.y3.invalid"])}})
L3 = B.rpc_day_limits("node_y3")
check("Y3c 노드 키 유료(버스트 없음) = 하루 몫과 창 남은 몫 중 작은 것(1,000)", L3.get("normal") == 1000 and L3.get("burst") == 1000, L3)
check("Y3d 노드 키 유료 장부도 날짜별 기록 31일 보관", B._RPC_DAY["node_y3"]["meter"].hist_keep >= 31, B._RPC_DAY["node_y3"]["meter"].hist_keep)

T.finish()
