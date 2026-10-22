#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths, statefile  # noqa: E402
import db as dbm  # noqa: E402
import ledger_backup as lb  # noqa: E402
import ledger_restore as LR  # noqa: E402

S = paths.STATE_DIR
chk = T.chk


def clear():
    for n in os.listdir(S):
        p = os.path.join(S, n)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(os.path.join(S, "inbox"), exist_ok=True)


def seg(stream, n):
    d = os.path.join(S, "inbox", stream)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{n:09d}.jsonl"), "w") as f:
        f.write(json.dumps({"kind": "x", "chain": stream}) + "\n")


def make_backup(path, offs):
    c = dbm.open_db(path)
    for s, (sg, off) in offs.items():
        c.execute("INSERT INTO inbox_offsets VALUES(?,?,?)", (s, sg, off))
    c.execute("INSERT INTO meta (k, v) VALUES ('backup_probe', '1')")
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()


clear()
chk(LR.streams_for(S) == ("evm", "sol", "bsc", "ex"), "B1 새 체인 상태 없음 = 복원 스트림 4개(종전)", LR.streams_for(S))
chk(list(LR.coverage({"evm": (1, 0)}, os.path.join(S, "inbox"))) == ["evm", "sol", "bsc", "ex"], "B1 인박스 판정 4줄(종전)")
chk(lb.prior_ledger_evidence(S) == [], "B1 흔적 없음 = 첫 설치(종전)")

clear()
statefile.atomic_write_json(os.path.join(S, "emitted_tron.json"), {"v": 1, "uids": {"ab" * 32: 1}})
ev = lb.prior_ledger_evidence(S)
chk(any("tron" in e for e in ev), "B2 새 체인 수집기 방출 기록 + 빈 인박스 = 예전 원장 흔적", ev)
clear()
statefile.atomic_write_json(os.path.join(S, "emitted_tron.json"), {})
chk(lb.prior_ledger_evidence(S) == [], "B2 빈 방출 기록 = 흔적 아님")

clear()
os.makedirs(os.path.join(S, "backups"))
BK = os.path.join(S, "backups", "ledger_20261010.db")
make_backup(BK, {"evm": (1, 0), "sol": (1, 0), "bsc": (1, 0), "ex": (1, 0), "tron": (2, 5), "sui": (1, 0)})
for s9 in ("evm", "sol", "bsc", "ex"):
    seg(s9, 1)
seg("tron", 4)
seg("sui", 1)
statefile.atomic_write_json(os.path.join(S, "cursor_tron.json"), {"v": 1, "lanes": {"history": {"cursor": "c9"}}})
statefile.atomic_write_json(os.path.join(S, "emitted_tron.json"), {"v": 1, "uids": {"x": 1}})
statefile.atomic_write_json(os.path.join(S, "cursor_sui.json"), {"v": 1})
p = LR.plan(BK)
chk(p["coverage"]["sui"]["state"] == "replay" and p["coverage"]["tron"]["state"] == "gap", "B3 새 체인 인박스 판정(sui 그대로 · tron gap)",
    {k: v["state"] for k, v in p["coverage"].items()})
chk(p["rewind"] == ["tron"], "B3 되감기 = gap 인 새 체인만", p["rewind"])
chk(p["files"] == {"cursor_tron.json": None, "emitted_tron.json": None}, "B3 tron 수집 커서·방출 기록 치움(창 처음부터 다시)", p["files"])
chk(any("Tron" in n for n in p["notes"]), "B3 안내 문구")
chk(os.path.exists(os.path.join(S, "cursor_tron.json")), "B3 미리보기는 파일 안 바꿈")

logs = []
clear()
statefile.atomic_write_json(os.path.join(S, "cursor_btc.json"), {"v": 1})
statefile.atomic_write_json(os.path.join(S, "emitted_btc.json"), {"v": 1, "uids": {}})
LR.new_ledger(False, fresh_collect=True, state_dir=S, log=logs.append, proc_check=False)
chk(any("cursor_btc.json" in x and "emitted_btc.json" in x for x in logs), "B4 새 원장 --fresh-collect = 새 체인 수집 기록도 옆으로", logs)
chk("btc_watch.py" in LR.COLLECTOR_UNITS and "unit_runner.py tron" in LR.COLLECTOR_UNITS and LR.COLLECTOR_UNITS[:5] == (
    "evm_watch.py", "sol_watch.py", "bsc_watch.py", "upbit_link.py", "ex_foreign.py"), "B4 수집기 정지 확인 목록(앞 5개 종전 그대로)")
chk("tron_watch.py" in LR.UNIT_SCRIPTS and LR.UNIT_SCRIPTS[0] == "core.py", "B4 복원 전 유닛 정지 확인 목록에 새 수집기")
T.finish()
