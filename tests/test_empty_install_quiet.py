#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402

import paths  # noqa: E402
import view_builder  # noqa: E402
import view_workers  # noqa: E402


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.recs = []

    def emit(self, r):
        self.recs.append(r)


CAP = _Cap()
logging.getLogger().addHandler(CAP)
logging.getLogger().setLevel(logging.DEBUG)
warns = lambda: [r.getMessage() for r in CAP.recs if r.levelno >= logging.WARNING]   # noqa: E731

with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f)
T.chk(not os.path.exists(paths.DB_PATH), "전제: 원장 DB 없음(빈 설치본)", paths.DB_PATH)


class _FakeB:
    lock = threading.Lock()
    SNAP_STALE_MAX = 120

    def __init__(self):
        self.snaps = type("S", (), {"cur": None})()


CAP.recs.clear()
r = T.safe(view_builder.StateBuilder.restore_snapfile, _FakeB())
T.chk(r is False, "Q1 원장 없음 = 저장본 끔(False)", r)
T.chk(not warns(), "Q1 원장 없음 = WARNING 0(스냅샷 저장본 서명 실패 소음 없음)", warns())


class _FakeW:
    cfg = {"chains": {"eth": {"blockscout": "https://eth.blockscout.invalid", "discovery": "explorer"}}, "wallets": []}
    _sale_queue = []
    _sale_queue_t = 0
    _sale_prio = []


CAP.recs.clear()
r = T.safe(view_workers.WorkersMixin._sale_refresh_once, _FakeW(), budget=0, get=lambda *a, **k: None)
T.chk(r == 0, "Q2 원장 없음 = 세일 워커 조회 0(예외 없음)", r)
T.chk(not warns(), "Q2 원장 없음 = WARNING 0", warns())

import db as dbm  # noqa: E402

c = dbm.open_db(paths.DB_PATH)
c.close()
w = _FakeW()
r = T.safe(view_workers.WorkersMixin._sale_refresh_once, w, budget=0, get=lambda *a, **k: None)
T.chk(isinstance(r, int) and w._sale_queue_t > 0, "Q3 원장 있음 = DB 열어 후보 큐 만듦(정상 경로)", (r, w._sale_queue_t))
T.finish()
