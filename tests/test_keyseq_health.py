#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import json
import os
import time

import common
import health

S = common.STATE_DIR
NOW = time.time()
SOLW = "So1" + "a" * 40
EVMW = "0x" + "b2" * 20


def wj(name, obj):
    os.makedirs(os.path.dirname(os.path.join(S, name)), exist_ok=True)
    common.atomic_write_json(os.path.join(S, name), obj)


def rm(name):
    try:
        os.remove(os.path.join(S, name))
    except OSError:
        pass


def set_env(helius: bool):
    with open(common.ENV_PATH, "w") as f:
        f.write("TJ_HELIUS_KEY=" + ("h" * 36 if helius else "") + "\n")


def state(cfg, age, runner, helius):
    json.dump(cfg, open(common.CONFIG_PATH, "w"))
    set_env(helius)
    if age is None:
        rm("cursor_sol.json")
        rm(os.path.join("health", "sol.json"))
    else:
        wj("cursor_sol.json", {SOLW: 123, "_synced_at": NOW - age})
        wj(os.path.join(health.HB_DIR, "sol.json"), {"schema": 1, "unit": "sol", "ts": int(NOW - age), "pid": 1,
                                                     "sources": {"sol": {"kind": "chain", "ok": True, "last_success_ts": NOW - age}}})
    if runner is None:
        rm("runner_sol.json")
    else:
        wj("runner_sol.json", dict({"unit": "sol", "pid": 1, "ts": int(time.time())}, **runner))
    c = common.load_config()
    st = {}
    health.collect_sources(c, st, NOW - (age or 0) - 60)
    obs = {"now": NOW, "sources": health.collect_sources(c, st, NOW), "hb": health.read_heartbeats(c), "keys": health.collect_keys(c, NOW)}
    items = health.evaluate(obs, dict(health.DEFAULTS, units=["tj-sol", "tj-core", "tj-web"]), ())
    lv = {i.get("id"): i.get("level") for i in items if isinstance(i, dict)}
    return sorted((k, v) for k, v in lv.items() if v in ("warn", "crit")), lv


CFG = {"chains": {}, "wallets": [{"type": "sol", "address": SOLW}], "sol": {"rpc": "helius"}}
WAIT_KEY = {"state": "waiting", "why": "Helius 키 없음(Solana 수집에 필요 — 무료 발급)"}
RUN = {"state": "running", "why": ""}

bad, lv = state(CFG, 3 * 3600, WAIT_KEY, False)
T.chk("sync:chain:sol" not in lv and "hb:tj-sol" not in lv, "K1 Helius 키 지움 = '동기화 멈춤'·'수집 루프 멈춤' 없음", bad)
T.chk(lv.get("key:helius") == "warn", "K1b Helius 키 지움 = 'Helius 키 필요' 주의 카드", bad)
T.chk(not any(v == "crit" for _k, v in bad), "K1c Helius 키 지움 = 빨강 0", bad)

bad, lv = state(CFG, 3 * 3600, RUN, True)
T.chk(lv.get("sync:chain:sol") == "crit", "K2 키 있고 러너 가동 · 커서 3시간 묵음 = 종전 '동기화 멈춤' 빨강", bad)
T.chk(lv.get("key:helius") == "ok", "K6 키 있음 = 카드 ok", lv.get("key:helius"))

bad, lv = state(CFG, 3 * 3600, None, False)
T.chk(lv.get("sync:chain:sol") == "crit", "K3 러너 기록 없음 = 종전 그대로(멈춤 경보)", bad)

bad, lv = state(CFG, None, WAIT_KEY, False)
T.chk(lv.get("key:helius") == "warn", "K4 처음부터 Helius 키 없음 = 'Helius 키 필요' 주의 카드(종전 표시 없음)", bad)

bad, lv = state(dict(CFG, sol={"rpc": "https://solana-rpc.invalid"}), None, RUN, False)
T.chk("key:helius" not in lv, "K5 공개 RPC 주소를 쓰는 설치 = 카드 없음", bad)

bad, lv = state(CFG, 3 * 3600, dict(WAIT_KEY), False)
wj("runner_sol.json", dict({"unit": "sol", "pid": 1, "ts": int(time.time()) - 300}, **WAIT_KEY))
c7 = common.load_config()
st7 = {}
health.collect_sources(c7, st7, NOW - 3 * 3600 - 60)
ids7 = {s.get("key") for s in health.collect_sources(c7, st7, NOW)}
T.chk("chain:sol" in ids7 and "sol" in health.read_heartbeats(c7), "K7 러너 기록 5분 묵음 = 대기로 안 봄(종전 감시)", sorted(ids7))

time.sleep(1.2)
bad, lv = state({"chains": {}, "wallets": [{"type": "evm", "chain": "eth", "address": EVMW}], "sol": {"rpc": "helius"}}, 3 * 3600,
                {"state": "waiting", "why": "Solana 지갑 없음"}, False)
T.chk("sync:chain:sol" not in lv and "hb:tj-sol" not in lv and "key:helius" not in lv, "K8 Solana 지갑 다 지움 = 멈춤 경보·키 카드 없음", bad)


def upbit(keys: bool):
    json.dump({"chains": {}, "wallets": []}, open(common.CONFIG_PATH, "w"))
    with open(common.ENV_PATH, "w") as f:
        f.write(("UPBIT_ACCESS=" + "a" * 20 + "\nUPBIT_SECRET=" + "s" * 20 + "\n") if keys else "UPBIT_ACCESS=\nUPBIT_SECRET=\n")
    for n in ("cursor_sol.json", "runner_sol.json", os.path.join("health", "sol.json")):
        rm(n)
    wj("upbit_balances.json", {"ts": NOW - 3 * 3600, "balances": []})
    wj("upbit_sync.json", {"last_ok": NOW - 3 * 3600})
    c = common.load_config()
    st = {}
    health.collect_sources(c, st, NOW - 4 * 3600)
    obs = {"now": NOW, "sources": health.collect_sources(c, st, NOW), "hb": health.read_heartbeats(c), "keys": health.collect_keys(c, NOW)}
    items = health.evaluate(obs, dict(health.DEFAULTS, units=["tj-ex", "tj-core", "tj-web"]), ())
    return {i.get("id"): i.get("level") for i in items if isinstance(i, dict)}


lv = upbit(False)
T.chk("sync:ex:upbit" not in lv, "K9 업비트 키 지움 = '업비트 동기화 멈춤' 없음", sorted((k, v) for k, v in lv.items() if v in ("warn", "crit")))
lv = upbit(True)
T.chk(lv.get("sync:ex:upbit") == "crit", "K10 업비트 키 있고 3시간 묵음 = 종전 '업비트 동기화 멈춤' 빨강", lv.get("sync:ex:upbit"))
T.finish()
