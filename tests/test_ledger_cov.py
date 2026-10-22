#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "ledger_cov.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/ledger_cov.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import ledger_cov as L  # noqa: E402

mp = os.path.join(T.ROOT, "dev", "refactor", "LEDGER_COV.json")
if os.path.isfile(mp):
    with open(mp, encoding="utf-8") as f:
        m = json.load(f)
    now = [(s["id"], s["lines"]) for s in L.sites(T.ROOT)]
    old = [(s["id"], s["lines"]) for s in m["sites"]]
    chk(now == old, "C1 저장소 지도 자리·줄 = 지금 src(바뀌면 ledger_cov all + report --out 다시)",
        {"지도에만": [x for x in old if x not in now][:5], "지금만": [x for x in now if x not in old][:5]})
    chk(set(m["summary"]) == {"target", "core_post", "demo"} and all(isinstance(v["not_executed"], list) for v in m["summary"].values()),
        "C1 지도 요약 칸(묶음 3 · 실행 0 목록)")
else:
    print("SKIP C1 저장소 지도 없음", flush=True)

A = '''import os
import subprocess
import sys


class M:
    def one(self, c, col):
        c.execute("UPDATE postings SET cost_usd=? WHERE posting_id=?", (1, 2))
        c.execute("UPDATE postings SET " + "cost_krw=? WHERE posting_id=?", (1, 2))
        c.execute(f"UPDATE postings SET {col}=? WHERE posting_id=?", (1, 2))
        c.execute("SELECT * FROM postings")
        c.execute("INSERT INTO meta (k, v) VALUES (1, 2)")

    def two(self, c, rows):
        for r in c.execute("SELECT 1 WHERE 0"):
            c.execute("INSERT OR IGNORE INTO positions (group_id) VALUES (?)"
                      " ", (r,))
        c.execute("DELETE FROM postings WHERE posting_id=?", (3,))


def three(c, flag):
    if flag: c.execute("UPDATE positions SET qty_norm=1")  # noqa: E701


def forked(c):
    pid = os.fork()
    if pid == 0:
        c = ["REPLACE INTO postings (posting_id) VALUES (9)"]   # 자식에선 sqlite 를 안 씀(맥 fork 뒤 sqlite = 비정상 종료)
        os._exit(0)
    os.waitpid(pid, 0)


def spawn():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
'''
root = os.path.join(T.TMP, "lcroot")
os.makedirs(os.path.join(root, "src"))
os.makedirs(os.path.join(root, "public", "tests"))
for name, body in (("a.py", A), ("core_post.py", 'X = "DELETE FROM positions WHERE g=1"\n'),
                   ("demo_data.py", 'def ledger(c):\n    c.execute("INSERT INTO postings (a) VALUES (1)")\n')):
    with open(os.path.join(root, "src", name), "w", encoding="utf-8") as f:
        f.write(body)
st = L.sites(root)
ids = [s["id"] for s in st]
chk(ids == ["a.py:M.one:UPDATE:postings#1", "a.py:M.one:UPDATE:postings#2", "a.py:M.one:UPDATE:postings#3",
            "a.py:M.two:INSERT:positions#1", "a.py:M.two:DELETE:postings#1", "a.py:three:UPDATE:positions#1", "a.py:forked:REPLACE:postings#1",
            "core_post.py:<모듈>:DELETE:positions#1", "demo_data.py:ledger:INSERT:postings#1"], "C2 자리 정의(글자·이음·f-string·줄 이음·INSERT OR·DELETE·REPLACE)", ids)
chk([s["group"] for s in st] == ["target"] * 7 + ["core_post", "demo"], "C2 묶음", [s["group"] for s in st])
chk([s["id"] for s in st if s["shared"]] == ["a.py:three:UPDATE:positions#1"], "C2 한 줄 if 자리 = shared(같은 줄 다른 문장 · 사람 확인)",
    [s["id"] for s in st if s["shared"]])
chk(st[2]["sql"] == "UPDATE postings SET {}=? WHERE posting_id=?" and st[1]["cols"] == "cost_krw", "C2 f-string 구멍 · 바꾸는 열", st[1:3])
ins = st[3]
chk(ins["lines"][0] != ins["lines"][1], "C2 줄 이은 호출 = 여러 줄 범위", ins["lines"])
root2 = os.path.join(T.TMP, "lcroot2")
os.makedirs(os.path.join(root2, "src"))
for name, body in (("core_post_cols.py", 'LEG_SQL = {\n    "one.1": "UPDATE postings SET cost_usd=?"\n        " WHERE posting_id=?",\n'
                                          '    "two.1": "DELETE FROM positions WHERE group_id=?",\n}\n'),
                   ("b.py", 'class K:\n    def one(self, n):\n        self._leg_sql("one.1", (1, 2))\n        self._leg_sql(n, ())\n'
                            '        self._leg_sql("없음.1", ())\n\n    def two(self):\n        self._leg_sql(\n            "two.1",\n            (3,))\n')):
    with open(os.path.join(root2, "src", name), "w", encoding="utf-8") as f:
        f.write(body)
st2 = L.sites(root2)
chk([(s["id"], s["lines"], s["cols"], s["group"]) for s in st2] == [("b.py:K.one:UPDATE:postings#1", [3, 3], "cost_usd", "target"),
                                                                   ("b.py:K.two:DELETE:positions#1", [8, 10], "", "target")]
    and st2[0]["sql"] == "UPDATE postings SET cost_usd=? WHERE posting_id=?",
    "C2 _leg_sql 부르기 = 표 글을 품은 자리(표 모듈 글은 자리 아님 · 표 밖 이름·변수 첫 인자 무시)", [(s["id"], s["lines"]) for s in st2])

SCRIPT = '''import os
import sqlite3
import sys
sys.path.insert(0, os.path.join(os.environ["TJ_TEST_ROOT"], "src"))
import a
c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, cost_usd, cost_krw)")
c.execute("CREATE TABLE positions (group_id)")
c.execute("CREATE TABLE meta (k, v)")
a.M().one(c, "cost_usd")
a.M().two(c, [])
a.three(c, 0)
a.forked(c)
a.spawn()
'''
with open(os.path.join(root, "public", "tests", "test_syn.py"), "w", encoding="utf-8") as f:
    f.write(SCRIPT)
out = os.path.join(T.TMP, "lcout")
with contextlib.redirect_stdout(io.StringIO()):
    res = L.all_tests(root, out, jobs=1)
chk(res.get("test_syn.py", {}).get("rc") == 0, "C3 합성 시험 rc 0", res)
rep = L.report(root, out)
by = {s["id"]: (s["tests"], s["fork_tests"]) for s in rep["sites"]}
chk(all(by[i] == (["test_syn.py"], []) for i in ids[:3]) and by["a.py:M.two:DELETE:postings#1"] == (["test_syn.py"], []),
    "C3 부른 함수의 자리 = 실행", by)
chk(by["a.py:M.two:INSERT:positions#1"] == ([], []), "C3 반복문 몸통(돌지 않음) 자리 = 실행 아님(머리 줄만으론 안 셈)", by["a.py:M.two:INSERT:positions#1"])
chk(by["a.py:forked:REPLACE:postings#1"] == ([], ["test_syn.py"]), "C3 os.fork 자식 실행 = fork_tests", by["a.py:forked:REPLACE:postings#1"])
chk(rep["summary"]["target"]["shared_line"] == ["a.py:three:UPDATE:positions#1"], "C3 요약에 같은 줄 다른 문장 자리 목록", rep["summary"]["target"])
chk(rep["children"].get("test_syn.py") == 1, "C3 subprocess 자식 = children 1", rep["children"])
chk(by["demo_data.py:ledger:INSERT:postings#1"] == ([], []) and rep["summary"]["demo"]["not_executed"] == ["demo_data.py:ledger:INSERT:postings#1"],
    "C3 안 부른 자리 = 실행 0 목록", rep["summary"])
chk(bool(L.all_tests.__code__) and os.path.isfile(os.path.join(out, "_run.json")), "C3 실행 기록 파일")
try:
    with contextlib.redirect_stdout(io.StringIO()):
        L.all_tests(root, out, jobs=1)
    chk(False, "C3 지난 판 폴더 재사용 거부")
except SystemExit:
    chk(True, "C3 지난 판 폴더 재사용 거부")

T.finish()
