#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import subprocess
import time

import common
import health
import unit_beat

S = common.STATE_DIR
NOW = time.time()
W = "0x" + "a1" * 20


def ck(name, cond, extra=None):
    T.chk(bool(cond), name, extra)


def wj(name, obj):
    os.makedirs(os.path.dirname(os.path.join(S, name)), exist_ok=True)
    common.atomic_write_json(os.path.join(S, name), obj)


def rm(name):
    try:
        os.remove(os.path.join(S, name))
    except FileNotFoundError:
        pass


json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "blocks_per_day": 7200, "rpcs": ["https://rpc.invalid"]}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W}]}, open(common.CONFIG_PATH, "w"))
os.makedirs(os.path.join(T.TMP, "logs"), exist_ok=True)
UNITS = list(health.UNITS)


def base_state(chain_ok=True, upbit_ok=True, prices=True):
    wj("cursor_evm_eth.json", dict({W: 100}, **({"_synced_at": NOW - 30} if chain_ok else {})))
    wj("upbit_balances.json", {"ts": NOW - 20})
    wj("upbit_sync.json", {"last_ok": NOW - 25} if upbit_ok else {"last_ok": 0})
    wj("exf_state.json", {"binance": {"backfilled_until": NOW - 100, "fills": {"backfilled_until": NOW - 100}}})
    wj("exf_active.json", {"active": ["binance"], "ts": NOW})
    wj("spot.json", {"updated": NOW - 10, "usd": {"BTC": 60000.0} if prices else {}, "usd_ts": {"BTC": NOW - 10} if prices else {},
                     "ex_usd": {"binance:BTC": 60000.0} if prices else {}, "ex_ts": {"binance:BTC": NOW - 10} if prices else {},
                     "dex_usd": {}, "dex_ts": {}, "want": {"ex": ["binance"], "dex": 0}})
    wj(os.path.join("backups", "backup_status.json"), {"created": NOW - 86400, "last_ok": NOW - 3600, "last_date": "20261009"})


def mem_first(keys, first):
    wj("health_eval.json", {"mem": {k: {"last": None, "first": first} for k in keys}})


PM2_ON = {u: {"status": "online", "restarts": 0, "pid": 100 + i, "uptime": NOW - 5000, "out": None, "err": None, "mem": 50 << 20}
          for i, u in enumerate(UNITS)}
PROBES = {"inbox": lambda: {}, "disk": lambda: {"free": 100 * 10 ** 9, "total": 200 * 10 ** 9}, "web": lambda: None, "tunnel": lambda: None}


def run_eval(mod, pm2):
    h = mod.settings(common.load_config())
    h["log_dir"] = os.path.join(T.TMP, "logs")
    m = mod.Monitor(probes=dict(PROBES, pm2=lambda: pm2))
    obs = m.observe(common.load_config(), h, NOW, False)
    return mod.evaluate(obs, h, open_ids={}), obs


SCEN = [("정상", dict(), None),
        ("체인 첫 성공 전 11분", dict(chain_ok=False), (["chain:eth"], NOW - 660)),
        ("빠른 수집기 모두 6분 성공 없음", dict(chain_ok=False, upbit_ok=False), (["chain:eth", "ex:upbit"], NOW - 360))]
for name, kw, mem in SCEN:
    for f9 in os.listdir(S):
        if f9.startswith("runner_"):
            os.remove(os.path.join(S, f9))
    base_state(**kw)
    if mem:
        mem_first(*mem)
    else:
        rm("health_eval.json")
    wj("runner_core.json", {"unit": "core", "pid": 999999, "ts": NOW - 400, "state": "running"})
    new_c, _o = run_eval(health, PM2_ON)
    ids = {c["id"] for c in new_c}
    ck(f"[1] pm2 있음 · {name}: 새 점검(collect:all)·'시작 뒤 성공 없음'·러너 생사가 끼지 않음",
       "collect:all" not in ids and not any("시작 뒤 성공 없음" in c["title"] for c in new_c)
       and all("러너 기록" not in str(c["detail"]) for c in new_c if c["id"].startswith("proc:")), [c for c in new_c if c["level"] in ("warn", "crit")])

base_state()
rm("health_eval.json")
for f9 in os.listdir(S):
    if f9.startswith("runner_"):
        os.remove(os.path.join(S, f9))
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
me = os.getpid()
wj("runner_core.json", {"unit": "core", "pid": me, "ts": NOW - 300, "state": "running"})
wj("runner_evm.json", {"unit": "evm", "pid": dead.pid, "ts": NOW - 20, "state": "running"})
wj("runner_sol.json", {"unit": "sol", "pid": me, "ts": NOW - 10, "state": "waiting", "why": "Helius 키 없음"})
wj("runner_bsc.json", {"unit": "bsc", "pid": me, "ts": NOW - 10, "state": "running", "by": "reload"})
for u9 in ("ex", "exf", "alert"):
    unit_beat.beat_once(u9, now=NOW - 5)
c2, o2 = run_eval(health, None)
P = {c["id"]: c for c in c2 if c["id"].startswith("proc:")}
ck("[2] ① 5분 묵은 러너 기록 = '프로세스 중지' 빨강", P["proc:tj-core"]["level"] == "crit" and P["proc:tj-core"]["title"] == "프로세스 중지", P["proc:tj-core"])
ck("[2] ① 기록은 새것인데 그 pid 가 없음 = 빨강", P["proc:tj-evm"]["level"] == "crit", P["proc:tj-evm"])
ck("[2] ① 살아 있는 대기 러너 = 초록(대기 사유 표시)", P["proc:tj-sol"]["level"] == "ok" and "대기" in P["proc:tj-sol"]["detail"], P["proc:tj-sol"])
ck("[2] ① 지원 감시기(by=reload) 기록 = 판정에 안 씀(확인 불가)", P["proc:tj-bsc"]["level"] is None, P["proc:tj-bsc"])
ck("[2] ① 업비트·해외·알림 유닛 = 생존 기록으로 초록", all(P[f"proc:tj-{u9}"]["level"] == "ok" for u9 in ("ex", "exf", "alert")),
   {u9: P[f"proc:tj-{u9}"] for u9 in ("ex", "exf", "alert")})
ck("[2] ① 기록 없는 유닛 = 종전처럼 '확인 불가'(수준 없음) · 선택 유닛(tj-review)은 빠짐", P["proc:tj-web"]["level"] is None and "proc:tj-review" not in P,
   (P["proc:tj-web"], "proc:tj-review" in P))
ck("[2] ① 생존 기록 파일 꼴 = runner_<유닛>.json {pid, ts, state, direct}", (lambda d: d["pid"] == me and d["direct"] is True and d["state"] == "running")(
   json.load(open(os.path.join(S, "runner_exf.json")))))
ck("[2] 중지 안내 = pm2 없이 다시 켜는 명령", "python3 src/unit_runner.py core" in P["proc:tj-core"]["action"], P["proc:tj-core"]["action"])

base_state(chain_ok=False)
mem_first(["chain:eth"], NOW - 660)
c3 = {c["id"]: c for c in run_eval(health, None)[0]}
ck("[3] ② pm2 없음 · 관측 11분째 한 번도 성공 없음 = 주황 '시작 뒤 성공 없음'", c3["sync:chain:eth"]["level"] == "warn" and "시작 뒤 성공 없음" in c3["sync:chain:eth"]["title"],
   c3["sync:chain:eth"])
mem_first(["chain:eth"], NOW - 300)
c3 = {c["id"]: c for c in run_eval(health, None)[0]}
ck("[3] ② 관측 5분째 = 아직 초록(10분 기다림)", c3["sync:chain:eth"]["level"] == "ok", c3["sync:chain:eth"])
base_state(chain_ok=False, upbit_ok=False)
mem_first(["chain:eth", "ex:upbit"], NOW - 360)
c3 = {c["id"]: c for c in run_eval(health, None)[0]}
ck("[3] ④ 빠른 수집기(체인·업비트) 모두 5분 넘게 성공 0 = 바로 주황 '모든 수집기 5분째 성공 없음'",
   c3.get("collect:all", {}).get("level") == "warn" and c3["collect:all"].get("persist") == 0, c3.get("collect:all"))
base_state()
mem_first(["chain:eth", "ex:upbit"], NOW - 360)
c3 = {c["id"]: c for c in run_eval(health, None)[0]}
ck("[3] ④ 하나라도 5분 안 성공 = 초록", c3.get("collect:all", {}).get("level") == "ok", c3.get("collect:all"))
mem_first(["chain:eth", "ex:upbit"], NOW - 100)
base_state(chain_ok=False, upbit_ok=False)
c3 = {c["id"]: c for c in run_eval(health, None)[0]}
ck("[3] ④ 관측 5분 전(막 켬) = 판정 안 함", "collect:all" not in c3, c3.get("collect:all"))

base_state(prices=False)
rm("health_eval.json")
src4 = {s["key"]: s for s in health.collect_sources(common.load_config(), {}, NOW)}
ck("[4] ③ 바퀴는 돌았는데(updated) 받은 시세 0 = 성공 아님(마지막 성공 없음)", src4["price:spot"]["last_success"] is None
   and "받은 시세 없음" in str(src4["price:spot"]["extra"]), src4["price:spot"])
base_state(prices=True)
src4 = {s["key"]: s for s in health.collect_sources(common.load_config(), {}, NOW)}
ck("[4] ③ 받은 시세 있음 = 종전처럼 성공", src4["price:spot"]["last_success"] == NOW - 10, src4["price:spot"])
wj("spot.json", {"updated": NOW - 10, "usd": {}, "ex_usd": {}, "dex_usd": {}, "want": {"ex": [], "dex": 0}})
src4 = {s["key"]: s for s in health.collect_sources(common.load_config(), {}, NOW)}
ck("[4] ③ 매길 보유가 없음(필요한 거래소·DEX 0) = 빈 시세가 정상(성공)", src4["price:spot"]["last_success"] == NOW - 10, src4["price:spot"])
T.finish()
