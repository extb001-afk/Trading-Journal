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
if not os.path.isfile(os.path.join(TOOLS, "sql_trace_ab.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/sql_trace_ab.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import sql_trace_ab as Q  # noqa: E402

chk(Q.norm_sql("UPDATE  postings SET a = ?,\n   b=?  WHERE x IS NULL ;") == Q.norm_sql("UPDATE postings SET a=?, b=? WHERE x IS NULL"),
    "Q1 공백·줄바꿈·구두점 둘레·끝 ; = 같은 글", Q.norm_sql("UPDATE  postings SET a = ?,\n   b=?  WHERE x IS NULL ;"))
chk(Q.norm_sql("SELECT 'a  b'") != Q.norm_sql("SELECT 'a b'"), "Q1 따옴표 안 공백은 그대로")
chk(Q.norm_sql("UPDATE postings SET a=? WHERE x IS NULL") != Q.norm_sql("UPDATE postings SET a=? WHERE x"), "Q1 조건 한 마디 = 다른 글")
chk(Q.write_table(Q.norm_sql("INSERT OR IGNORE INTO postings (a) VALUES (?)")) == "postings" and Q.write_table("DELETE FROM positions WHERE g=?") == "positions"
    and Q.write_table("SELECT * FROM postings") is None, "Q1 쓰기 표 이름(INSERT OR · DELETE · 읽기 = 없음)")
chk(bool(Q.site_rx("UPDATE postings SET {}=? WHERE id=?").match(Q.norm_sql("UPDATE postings SET cost_usd = ? WHERE id=?"))),
    "Q1 자리 꼴(f-string 구멍)과 녹화 글 맞춤")

MOD = '''import sqlite3


def setup(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS postings (posting_id INTEGER PRIMARY KEY, cost_usd TEXT, cost_krw TEXT, event_ts INT)")
    c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    c.execute("INSERT INTO meta (k, v) VALUES ('made', '1')")
    c.commit()
    return c


class PxMixin:
    def price(self, c):
        c.execute("INSERT INTO postings (posting_id, cost_usd, event_ts) VALUES (1, NULL, 5)")
        c.execute("UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=? AND cost_usd IS NULL", ("1.5", "2000", 1))
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('stamp', ?)", ("1",))
        c.commit()
'''
SCRIPT = '''import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.environ["TJ_TEST_ROOT"], "src"))
import mod
d = tempfile.mkdtemp()
c = mod.setup(os.path.join(d, "ledger.db"))
mod.PxMixin().price(c)
'''
UPD = 'c.execute("UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=? AND cost_usd IS NULL", ("1.5", "2000", 1))'
VARIANTS = {
    "ws": MOD.replace(UPD, 'c.execute("""UPDATE  postings\n            SET cost_usd = ?,  cost_krw=?\n            WHERE posting_id=? AND cost_usd IS NULL""",'
                           ' ("1.5", "2000", 1))'),
    "noisnull": MOD.replace(" AND cost_usd IS NULL", ""),
    "params": MOD.replace('("1.5", "2000", 1)', '("2000", "1.5", 1)'),
    "commit": MOD.replace(UPD, "c.commit()\n        " + UPD),
    "nometa": MOD.replace('        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (\'stamp\', ?)", ("1",))\n', ""),
    "rename": MOD.replace("def price(self, c):", "def price(self, c):\n        return self.price_v2(c)\n\n    def price_v2(self, c):"),
    "helper": MOD.replace(UPD, 'import ledgermod\n        ledgermod.run(c, "UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=? AND cost_usd IS NULL",'
                               ' ("1.5", "2000", 1))'),
    "never": MOD + '\n    def never(self, c):\n        c.execute("UPDATE postings SET event_ts=? WHERE posting_id=?", (9, 1))\n',
}
HELPER = "def run(c, sql, params):\n    return c.execute(sql, params)\n"
td = os.path.join(T.TMP, "qtests")
os.makedirs(td)
for n, body in (("test_syn.py", SCRIPT), ("test_none.py", "x = 1\n"),
                ("test_meta.py", SCRIPT.replace("mod.PxMixin().price(c)\n", "")),
                ("test_factory.py", 'import sqlite3\nclass C(sqlite3.Connection):\n    pass\nc = sqlite3.connect(":memory:", factory=C)\n'
                                    'c.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY)")\nc.execute("INSERT INTO postings VALUES (1)")\n'),
                ("test_script.py", 'import sqlite3.dbapi2\nc = sqlite3.dbapi2.connect(":memory:")\n'
                                   'c.execute("CREATE TABLE postings (posting_id INTEGER PRIMARY KEY)")\n'
                                   'c.executescript("INSERT INTO postings (posting_id) VALUES (5); SELECT \'a;b\';")\n'),
                ("test_opendb.py", 'import os\nimport sys\nimport tempfile\nd = tempfile.mkdtemp()\nos.environ["TJ_BASE"] = d\n'
                                   'sys.path.insert(0, os.path.join(os.environ["TJ_TEST_ROOT"], "src"))\nimport db\n'
                                   'c = db.open_db(os.path.join(d, "ledger.db"))\n'
                                   'c.execute("INSERT INTO meta (k, v) VALUES (\'q4\', \'1\')")\nc.commit()\n'
                                   'c.execute("DELETE FROM postings WHERE posting_id=?", (7,))\nc.commit()\n')):
    with open(os.path.join(td, n), "w", encoding="utf-8") as f:
        f.write(body)


def root(name, body):
    r = os.path.join(T.TMP, "root_" + name)
    os.makedirs(os.path.join(r, "src"))
    with open(os.path.join(r, "src", "mod.py"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(r, "src", "ledgermod.py"), "w", encoding="utf-8") as f:
        f.write(HELPER)
    return r


def go(r, out, tests):
    with contextlib.redirect_stdout(io.StringIO()):
        Q.run(r, td, os.path.join(T.TMP, out), tests, jobs=2, timeout=120)
    return os.path.join(T.TMP, out)


def cmp(a, b, moved=None, allow=None):
    head, diffs, same, hit = Q.compare(a, b, moved, allow)
    return head, diffs, same


RA = root("a", MOD)
A = go(RA, "out_a", ["test_syn.py"])
A2 = go(root("a2", MOD), "out_a2", ["test_syn.py"])
h, d, s = cmp(A, A2)
chk(not h and not d and s == 1, "Q2 그대로(같은 글 다른 뿌리) = 같음", {"head": h, "diff": d})
with open(os.path.join(A, "test_syn.py.json"), encoding="utf-8") as f:
    ja = json.load(f)
led = [e for e in ja["events"] if e.get("led")]
chk(len(led) == 2 and led[0]["f"].startswith("mod.py:PxMixin.price") and all(e["tx"] == led[0]["tx"] for e in led),
    "Q2 녹화 = 원장 쓰기 2 · 함수 칸 mod.py:PxMixin.price · 같은 거래", led)
chk(any(e["k"] == "t" and e["s"].startswith("BEGIN") for e in ja["events"]) and any(e["k"] == "t" and e["s"] == "COMMIT" for e in ja["events"]),
    "Q2 암묵 BEGIN·COMMIT 경계 녹화(set_trace_callback)")
for name, want in (("ws", "same"), ("noisnull", "(1)"), ("params", "(1)"), ("commit", "(2)"), ("nometa", "(2)"), ("rename", "(3)"), ("helper", "(3)")):
    B = go(root(name, VARIANTS[name]), "out_" + name, ["test_syn.py"])
    h, d, s = cmp(A, B)
    if want == "same":
        chk(not h and not d and s == 1, "Q2 %s = 같음" % name, {"head": h, "diff": d})
    else:
        chk(not h and len(d) == 1 and want in d[0], "Q2 %s = 차이 %s" % (name, want), {"head": h, "diff": d})
    if name == "rename":
        h2, d2, s2 = cmp(A, B, moved={"rename": {"mod.py:PxMixin.price_v2": "mod.py:PxMixin.price"}})
        chk(not h2 and not d2, "Q2 rename + 옮긴 자리 표 = 같음", d2)
    if name == "helper":
        h2, d2, s2 = cmp(A, B, moved={"skip": ["ledgermod.py:*"]})
        chk(not h2 and not d2, "Q2 helper + 건너뛸 프레임 표 = 같음", d2)

N1 = go(RA, "out_none_a", ["test_none.py"])
N2 = go(RA, "out_none_b", ["test_none.py"])
h, d, s = cmp(N1, N2)
chk(any("연결을 하나도" in x for x in h), "Q3 갈고리 연결 0 = 머리 실패", h)
M1 = go(RA, "out_meta_a", ["test_meta.py"])
M2 = go(RA, "out_meta_b", ["test_meta.py"])
h, d, s = cmp(M1, M2)
chk(any("빈 녹화" in x for x in h), "Q3 원장 쓰기 녹화 0 = 머리 실패(빈 녹화끼리 같음 아님)", h)
RN = root("never", VARIANTS["never"])
V1 = go(RN, "out_never_a", ["test_syn.py"])
V2 = go(RN, "out_never_b", ["test_syn.py"])
h, d, s = cmp(V1, V2)
chk(any("mod.py:PxMixin.never:UPDATE:postings#1" in x for x in h), "Q3 대상 자리 녹화 0 = 머리 실패", h)
h, d, s = cmp(V1, V2, allow={"mod.py:PxMixin.never:UPDATE:postings#1": "실행 증거 없음"})
chk(not h and not d and s == 1, "Q3 허용 표 + 이유 = 통과", h)
h, d, s = cmp(V1, V2, allow={"mod.py:PxMixin.never:UPDATE:postings#1": " "})
chk(bool(h), "Q3 허용 표 이유 빈칸 = 실패", h)

F1 = go(RA, "out_fac_a", ["test_factory.py"])
F2 = go(RA, "out_fac_b", ["test_factory.py"])
h, d, s = cmp(F1, F2)
chk(any("갈고리 밖" in x for x in h), "Q3 다른 factory 연결(갈고리 밖) = 머리 실패(양쪽 같아도)", h)

O = go(T.ROOT, "out_opendb", ["test_opendb.py"])
with open(os.path.join(O, "test_opendb.py.json"), encoding="utf-8") as f:
    jo = json.load(f)
ev = jo["events"]
dele = [e for e in ev if e.get("led") and e["s"].startswith("DELETE FROM postings")]
chk(jo.get("conns", 0) >= 1 and len(dele) == 1 and dele[0]["c"] == "ledger.db#1", "Q4 db.open_db 연결의 postings 쓰기 녹화", {"conns": jo.get("conns"), "led": dele})
chk(any(e["k"] == "x" and e["s"].startswith("CREATE TABLE IF NOT EXISTS postings") for e in ev)
    and any(e["k"] == "x" and e["s"].startswith("INSERT INTO meta") and str(e.get("p")).startswith("h:") for e in ev),
    "Q4 open_db 의 DDL·meta 쓰기도 기록(비원장 = 매개변수 해시)")
chk(jo.get("rc") == 0 and jo.get("hashseed") == "0", "Q4 자식 rc 0 · 해시 시드 0", {"rc": jo.get("rc"), "hs": jo.get("hashseed")})

S = go(T.ROOT, "out_script", ["test_script.py"])
with open(os.path.join(S, "test_script.py.json"), encoding="utf-8") as f:
    js = json.load(f)
led = [e for e in js["events"] if e.get("led")]
chk(js.get("conns") == 1 and [e["s"] for e in led] == ["INSERT INTO postings(posting_id)VALUES(5)"],
    "Q4 sqlite3.dbapi2.connect 도 갈고리 · executescript 안 원장 쓰기 = 문장마다 녹화(따옴표 안 ; 는 안 자름)", {"conns": js.get("conns"), "led": led})
chk(Q.split_script("A; B 'x;y' ;;C") == ["A", "B 'x;y'", "C"], "Q1 대본 자르기(따옴표 안 ; 유지 · 빈 문장 버림)", Q.split_script("A; B 'x;y' ;;C"))

T.finish()
