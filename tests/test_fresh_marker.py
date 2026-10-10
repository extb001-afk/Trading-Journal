#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest

import json
import os

import common
import core

chk = T.chk
core.dm = lambda *a, **k: None
W = "0x" + "a1" * 20
cfg = {"chains": {"eth": {"blockscout": "https://eth.example.invalid", "conf_depth": 12, "blocks_per_day": 7200}},
       "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "t"}], "backfill_months": 1}
with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f)
MARK = os.path.join(common.STATE_DIR, "backfill_done")


def env(keys: bool, extra: str = ""):
    with open(common.ENV_PATH, "w", encoding="utf-8") as f:
        f.write(("UPBIT_ACCESS=synthetic-access\nUPBIT_SECRET=synthetic-secret\n" if keys else "TJ_ETHERSCAN_KEY=\n") + extra)


def run(c):
    c._recon_pass_scopes(set(), False, {})
    return os.path.exists(MARK)


def reset(c, eth_done: bool, up_done: bool):
    if os.path.exists(MARK):
        os.remove(MARK)
    c.conn.execute("DELETE FROM meta WHERE k IN ('recon_done_eth','recon_done_upbit','recon_done_exf_binance')")
    if eth_done:
        c.conn.execute("INSERT INTO meta (k, v) VALUES ('recon_done_eth', '1700000000')")
    if up_done:
        c.conn.execute("INSERT INTO meta (k, v) VALUES ('recon_done_upbit', '1700000000')")
    c.conn.commit()


c = core.Core(common.load_config())
c.conn.commit()

env(False)
reset(c, True, False)
chk(run(c), "F1 업비트 키 없음 + 지갑 체인 대사 끝 → 백필 완료 마커 생성")

env(True)
reset(c, True, False)
chk(not run(c), "F2 업비트 키 있음 + 업비트 대사 전 → 마커 없음(종전 그대로)")

reset(c, True, True)
chk(run(c), "F3 업비트 키 있음 + 업비트 대사 끝 → 마커 생성")

env(False)
reset(c, False, False)
chk(not run(c), "F4 지갑 체인 대사 전 → 업비트 키가 없어도 마커 없음")

env(False, "TJ_BINANCE_KEY=synthetic-k\nTJ_BINANCE_SECRET=synthetic-s\n")
reset(c, True, False)
chk(not run(c), "F7 업비트 없음 + 바이낸스 키 · 바이낸스 첫 대사 전 → 마커 없음")
c.conn.execute("INSERT INTO meta (k, v) VALUES ('recon_done_exf_binance', '1700000000')")
c.conn.commit()
chk(run(c), "F7b 바이낸스 첫 대사 끝 → 마커 생성")
env(False, "TJ_BINANCE_KEY=synthetic-k\n")
reset(c, True, False)
chk(run(c), "F7c 키 칸 일부만(시크릿 없음) = 연결 아님 → 기다리지 않음")
env(False)

import sqlite3
import web


class Fake:
    cfg = {"chains": {"eth": {}, "base": {}, "optimism": {}, "robinhood": {}},
           "wallets": [{"type": "evm", "chain": "eth", "address": W}]}
    _bf_jobs = staticmethod(web.StateBuilder._bf_jobs)
    _backfill_progress = web.StateBuilder._backfill_progress


if os.path.exists(MARK):
    os.remove(MARK)
common.atomic_write_json(os.path.join(common.STATE_DIR, "cursor_evm_eth.json"), {W: 123})
mc = sqlite3.connect(":memory:")
mc.execute("CREATE TABLE meta (k TEXT, v TEXT)")
env(False)
bp = Fake()._backfill_progress(mc)
chk(bp is not None and "대사 0/1" in bp["detail"] and "optimism" not in (bp.get("remain") or "") and "upbit" not in (bp.get("remain") or "")
    and "sol" not in (bp.get("remain") or ""), "F5 대사 분모 = 지갑 있는 체인만(업비트 키 없음)", bp)
chk(bp is not None and bp["pct"] == 99, "F6 BSC 지갑 없음 → 수집 100% (대사 남아 99 캡)", bp)
env(True)
bp = Fake()._backfill_progress(mc)
chk(bp is not None and "대사 0/2" in bp["detail"] and "upbit" in (bp.get("remain") or ""), "F5b 업비트 키 있음 → 업비트 대사가 분모에", bp)
mc.execute("INSERT INTO meta VALUES ('recon_done_eth', '1')")
env(False)
bp = Fake()._backfill_progress(mc)
chk(bp is not None and "대사 1/1" in bp["detail"] and bp["pct"] == 100, "F5c 지갑 체인 대사 끝(업비트 키 없음) → 1/1 · 100%", bp)

T.finish()
