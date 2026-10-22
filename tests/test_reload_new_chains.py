import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths, statefile  # noqa: E402
import chain_registry as reg  # noqa: E402
import wallet_register as wr  # noqa: E402
import bf_engine  # noqa: E402
import _rpcfake  # noqa: E402
_rpcfake.loop_open(bf_engine, T)
if not os.path.isfile(os.path.join(T.ROOT, "tools", "wallet_reload_watch.py")):
    print("SKIP tools/wallet_reload_watch.py 없음(공개판 — 유닛 러너가 재시작)")
    T.finish()
import wallet_reload_watch as rw  # noqa: E402

BASE = {"chains": {"eth": {"rpcs": ["http://127.0.0.1:9/synthetic"]}}, "wallets": [], "chain_wallets": []}
ADDR = {"tron": "41" + "11" * 20, "sui": "0x" + "21" * 32, "ton": "0:" + "31" * 32, "btc": "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"}
NOW = time.time()
STARTED = {u: NOW - 3600 for u in wr.RELOAD_UNITS}
CALLS = []
_real_run = subprocess.run


def fake_run(argv, **kw):
    if not (isinstance(argv, list) and argv and argv[0] == "fake-pm2"):
        return _real_run(argv, **kw)
    CALLS.append(list(argv))
    out = json.dumps([{"name": u, "pm2_env": {"status": "online", "pm_uptime": t * 1000}} for u, t in STARTED.items()]) \
        if argv[1] == "jlist" else ""
    return subprocess.CompletedProcess(argv, 0, out, "")


os.environ["PM2_BIN"] = "fake-pm2"
rw.subprocess.run = fake_run


def reset():
    for n in os.listdir(paths.STATE_DIR):
        p = os.path.join(paths.STATE_DIR, n)
        if os.path.isfile(p):
            os.unlink(p)
    statefile.atomic_write_json(paths.CONFIG_PATH, BASE)


def restarts_since(n):
    return [c for c in CALLS[n:] if c[1] == "restart"]


try:
    T.chk(all(reg.spec(c).unit in rw.UNIT_KEY and rw.UNIT_KEY[reg.spec(c).unit] == c for c in reg.CHAINS),
          "UNIT_KEY 에 새 체인 유닛 → 하트비트 키(체인 이름)", rw.UNIT_KEY)

    for ch in reg.CHAINS:
        reset()
        w = rw.Watch()
        n0 = len(CALLS)
        wr.register_chain_wallet(ch, address=ADDR[ch], source="test")
        wr.register_wallet("0x" + "42" * 20, ["eth"], "합성 EVM", source="test")
        got = [T.safe(w.tick, NOW + 30 + i * 15) for i in range(3)]
        rs = restarts_since(n0)
        T.chk(got[0] == "restarted" and len(rs) == 1 and ("tj-" + ch) in rs[0] and "tj-evm" in rs[0] and not wr.pending_requests(),
              f"{ch}: 새 체인+EVM 동시 요청 → 합집합 재시작 1번·미처리 0", {"ticks": got, "restarts": rs, "pend": len(wr.pending_requests())})

    for ch in reg.CHAINS:
        reset()
        w = rw.Watch()
        n0 = len(CALLS)
        wr.register_chain_wallet(ch, address=ADDR[ch], source="test-runner")
        hb = os.path.join(paths.STATE_DIR, f"runner_{ch}.json")
        statefile.atomic_write_json(hb, {"ts": NOW + 120, "unit": ch, "state": "running", "fp": "owned", "pid": 1})
        got = T.safe(w.tick, NOW + 130)
        rs = restarts_since(n0)
        T.chk(got == "restarted" and all(("tj-" + ch) not in c for c in rs) and statefile.read_json(hb, {}).get("fp") == "owned",
              f"{ch}: unit_runner 소유 = 재시작 안 함·하트비트 그대로", {"got": got, "restarts": rs})
        reset()
        gone = STARTED.pop("tj-" + ch)
        try:
            w = rw.Watch()
            n0 = len(CALLS)
            wr.register_chain_wallet(ch, address=ADDR[ch], source="test-absent")
            got = T.safe(w.tick, NOW + 130)
            rs = restarts_since(n0)
            T.chk(got == "restarted" and all(("tj-" + ch) not in c for c in rs) and w.fp.get(ch) is None,
                  f"{ch}: pm2 에 없는 유닛 = 새로 안 켬·적용 표시 안 함", {"got": got, "restarts": rs, "fp": w.fp.get(ch)})
        finally:
            STARTED["tj-" + ch] = gone

    reset()
    w = rw.Watch()
    wr.register_chain_wallet("tron", address=ADDR["tron"], source="test-retry")

    def fail_run(argv, **kw):
        r = fake_run(argv, **kw)
        if isinstance(argv, list) and argv[:2] == ["fake-pm2", "restart"]:
            r.returncode = 1
        return r
    rw.subprocess.run = fail_run
    got = [T.safe(w.tick, NOW + 130 + i * 15) for i in range(3)]
    rw.subprocess.run = fake_run
    st = statefile.read_json(rw.STATUS_PATH, {})
    T.chk(got == ["fail"] * 3 and st.get("level") == "warn" and len(wr.pending_requests()) == 1,
          "tron: 재시작 실패 3회 = 요청 유지·경고", {"got": got, "st": st})
    got = T.safe(w.tick, NOW + 190)
    T.chk(got == "restarted" and not wr.pending_requests() and statefile.read_json(rw.STATUS_PATH, {}).get("level") == "ok",
          "tron: 다음 성공 = 요청·경고 정리", got)

    reset()
    w = rw.Watch()
    wr.register_wallet("0x" + "43" * 20, ["eth"], "합성 대조", source="test")
    got = T.safe(w.tick, NOW + 90)
    T.chk(got == "restarted" and not wr.pending_requests(), "EVM 만 등록 = 종전대로 재시작", got)
finally:
    rw.subprocess.run = _real_run

T.finish()
