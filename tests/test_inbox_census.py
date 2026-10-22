#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not (os.path.isfile(os.path.join(TOOLS, "inbox_census.py")) and os.path.isfile(os.path.join(TOOLS, "inbox_ab.py"))):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/inbox_census.py · inbox_ab.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import inbox_ab as B  # noqa: E402
import inbox_census as C  # noqa: E402


def J(rec):
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def mk(name, segs):
    d = os.path.join(T.TMP, name)
    for st, lines in segs.items():
        os.makedirs(os.path.join(d, st), exist_ok=True)
        with open(os.path.join(d, st, "000000001.jsonl"), "wb") as f:
            f.write(b"".join(lines))
    return d


clean = mk("ib_clean", {"evm": [J({"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": "0xa"}), J({"kind": "evm_tx", "v": 1, "txhash": "0xb", "chain": "eth"})],
                        "ex": [J({"v": 1, "kind": "ex_fills", "exchange": "upbit", "orders": []}), J({"v": 1, "kind": "ex_fills", "note": "한글"})]})
c0 = C.census(clean)
chk(c0["lines"] == 4 and c0["corrupt"] == 0 and c0["kinds"] == {"evm_tx": 2, "ex_fills": 2}
    and c0["streams"] == {"evm": {"evm_tx": 2}, "ex": {"ex_fills": 2}}, "N1 스트림·종류별 수", c0)
chk(c0["key_orders"] == {"evm_tx": 2, "ex_fills": 2} and c0["roundtrip_diff"] == {} and c0["v"]["evm_tx"] == {"1": 2}, "N1 열쇠 순서 종류 · 왕복 같음 · v", c0)
chk(C.verdict(c0, T.ROOT) == [], "N2 깨끗한 폴더 = 통과(종류 ⊆ 계약 표)", C.verdict(c0, T.ROOT))
dirty = mk("ib_dirty", {"evm": [J({"v": 1, "kind": "evm_tx"}), b'{"kind": "evm_tx", \n', b'{"v": 1, "kind": "evm_tx"}\n',
                                json.dumps({"v": 1, "kind": "evm_tx", "n": "한"}).encode() + b"\n", J({"v": 2, "kind": "sol_tx"}),
                                J({"v": 1, "kind": "zz_new"}), b'{"v": 1, "kind": "evm_tx"']})
c1 = C.census(dirty)
chk(c1["corrupt"] == 1 and c1["partial_tail"] == 1 and c1["lines"] == 6, "N1 깨진 줄 1 · 끝 줄바꿈 없는 줄 = 셈 밖", c1)
chk(c1["roundtrip_diff"] == {"evm_tx": 2}, "N1 왕복 다름(공백 · ensure_ascii)", c1["roundtrip_diff"])
bad = C.verdict(c1, T.ROOT)
chk(any("깨진 줄" in x for x in bad) and any("왕복" in x for x in bad) and any("v ≠ 1" in x for x in bad)
    and any("zz_new" in x for x in bad), "N2 깨진 줄·왕복·v≠1·계약 표에 없는 종류 = 실패", bad)
c2 = dict(c0, kinds={"evm_tx": 3, "ex_fills": 2})
chk(any("지난 판과 다름: kinds" in x for x in C.verdict(c2, None, c0)) and C.verdict(c0, None, c0) == [], "N2 지난 판과 다름 = 실패 · 같음 = 통과")

gout = os.path.join(os.path.expanduser("~"), "tj_golden", "out")
for p, why in ((os.path.join(T.TMP, "x", "c.json"), "out 밖"), (os.path.join(gout, "base_x", "c.json"), "base 이름"),
               (os.path.join(gout, "ra1", "c.json"), "ra1"), (os.path.join(gout, "gate_x", "c.json"), "gate_ 이름"),
               (os.path.join(gout, "c.json"), "out 바로 아래 파일"), (os.path.join(gout, "..", "base0", "c.json"), "경로 이동")):
    try:
        C.safe_out(p)
        chk(False, "N3 출력 경로 거부: %s" % why)
    except SystemExit:
        chk(True, "N3 출력 경로 거부: %s" % why)

for nm in ("base9", "ra1", "a/b", "..", "", "gate_x"):
    try:
        B._out_dir(nm)
        chk(False, "N4 이름 거부 %r" % nm)
    except SystemExit:
        chk(True, "N4 이름 거부 %r" % nm)


def ledger(path, rows, extra=None, skip=()):
    con = sqlite3.connect(path)
    for t in B.REQUIRED + ("other_tab",):
        if t not in skip:
            con.execute("CREATE TABLE %s (%s)" % (t, "posting_id INTEGER PRIMARY KEY, a, b" if t == "postings" else "a, b"))
    con.executemany("INSERT INTO postings (posting_id, a, b) VALUES (?,?,?)", rows)
    if extra is not None:
        con.execute("INSERT INTO other_tab (a, b) VALUES (?, ?)", extra)
    con.commit()
    con.close()
    return path


f1 = B.fingerprint(ledger(os.path.join(T.TMP, "l1.db"), [(1, "x", 1), (2, "y", 2)]))
f2 = B.fingerprint(ledger(os.path.join(T.TMP, "l2.db"), [(7, "y", 2), (9, "x", 1)]))
f3 = B.fingerprint(ledger(os.path.join(T.TMP, "l3.db"), [(1, "x", 1), (2, "y", 3)]))
f4 = B.fingerprint(ledger(os.path.join(T.TMP, "l4.db"), [(1, "x", 1), (2, "y", 2)], extra=(1, 2)))
chk(f1 == f2, "N4 지문 = 자동 번호 빼고 행 내용(차례 무관)", [f1["postings"], f2["postings"]])
chk(f1["postings"] != f3["postings"] and f1["meta"] == f3["meta"] and f1["postings"]["n"] == 2, "N4 한 칸 바뀌면 다름", [f1["postings"], f3["postings"]])
chk(f1 != f4 and f4["other_tab"]["n"] == 1 and set(f1) == set(B.REQUIRED) | {"other_tab"},
    "N4 지문 = 원장의 모든 표(목록 밖 표의 쓰기도 다름 · exf_late_pending 필수)", sorted(f4))
chk(B.DROP == {"postings": {"posting_id"}, "transfers": {"transfer_id", "id"}, "raw_rewrites": {"at"}},
    "N4 빼는 열 = 닫힌 목록(자동 번호 + sqlite 'now' 트리거 시각 한 열 · meta 무시 0)", B.DROP)
try:
    B.fingerprint(ledger(os.path.join(T.TMP, "l5.db"), [], skip=("exf_late_pending",)))
    chk(False, "N4 필수 표 없음 = 거부")
except SystemExit:
    chk(True, "N4 필수 표 없음 = 거부")

import subprocess  # noqa: E402
env = {k: v for k, v in os.environ.items() if not k.startswith(("TJ_", "PYTHON", "INBOXAB_"))}
for why, extra_env in (("TJ_BASE 없음", {}), ("TJ_BASE = 임의 폴더", {"TJ_BASE": T.TMP, "TJ_CONFIG": os.path.join(T.TMP, "config.json")}),
                       ("동결 원본 자리", {"TJ_BASE": os.path.join(os.path.expanduser("~"), "tj_golden", "base0"),
                                       "TJ_CONFIG": os.path.join(os.path.expanduser("~"), "tj_golden", "base0", "config.json")})):
    e2 = dict(env, **extra_env)
    e2["PYTHONPATH"] = os.path.join(T.TMP, "no_such_src")
    p = subprocess.run([sys.executable, "-s", os.path.join(TOOLS, "inbox_ab.py"), "drive", os.path.join(T.TMP, "drive_out.json")],
                       env=e2, capture_output=True, text=True, timeout=60)
    chk(p.returncode == 2 and "drive 거부" in p.stderr and not os.path.exists(os.path.join(T.TMP, "drive_out.json")),
        "N4 drive 입구 거부: %s" % why, {"rc": p.returncode, "err": p.stderr[-300:]})

T.finish()
