#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import importlib  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "like_proof.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/like_proof.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import like_proof as LP  # noqa: E402

sites = LP.find_sites(T.SRC)
n = {k: sum(1 for s in sites if s["kind"] == k) for k in ("lit", "param")}
chk(n == {"lit": 10, "param": 21}, "L1 자리 = 리터럴 10 · 매개변수 21(6-5 뒤 남은 자리)", n)
chk(LP.check_sites(sites) == [], "L1 자리 표 문제 0(수·템플릿·앵커)", LP.check_sites(sites))
chk(len({s["id"] for s in sites}) == len(sites), "L1 자리 이름 겹침 0")

import search_index  # noqa: E402
VEC = ["a_b", "50%", "x\\y", "_%\\", "plain", "", "wrecon_done:eth:0xab_", "%:disc:%"]
chk(all(LP._like_escape_candidate(v) == search_index._lesc(v) for v in VEC), "L2 후보 like_escape = search_index._lesc")
import textutil  # noqa: E402
chk(all(textutil.like_escape(v) == LP._like_escape_candidate(v) for v in VEC + list(LP._LE_VEC)), "L2 textutil.like_escape = 후보 규칙")
_fn = LP.bind_like_escape(T.SRC)
chk(LP.LIKE_ESCAPE is _fn and _fn.__module__ == "_like_proof_textutil" and all(_fn(v) == textutil.like_escape(v) for v in VEC),
    "L2 연결 지점 = --src 의 textutil.like_escape(6-5)")

chk(LP.lit_new("'recon_done_%'") == "'recon\\_done\\_%' ESCAPE '\\'", "L3 리터럴 이스케이프", LP.lit_new("'recon_done_%'"))
chk(LP.lit_new("'it''s_%'") == "'it''s\\_%' ESCAPE '\\'", "L3 리터럴 안 작은따옴표 그대로", LP.lit_new("'it''s_%'"))
chk(LP.param_new("pre", "wrecon_done:a_b:%") == ("wrecon_done:a_b:", "wrecon\\_done:a\\_b:%"), "L3 pre 꼴", LP.param_new("pre", "wrecon_done:a_b:%"))
chk(LP.param_new("suf", "%:0xab_") == (":0xab_", "%:0xab\\_"), "L3 suf 꼴")
chk(LP.param_new("mid", '%"a_b"%') == ('"a_b"', '%"a\\_b"%'), "L3 mid 꼴")
chk(LP.param_new("out_mid", "out:%:a_b") == (":a_b", "out:%:a\\_b"), "L3 out_mid 꼴(가운데 와일드카드)")
chk(LP.param_new("wallet_mid", "wallet:%:a%b") == (":a%b", "wallet:%:a\\%b"), "L3 원 입력 안 '%' = 글자로")
chk(LP.param_new("pre", "abc") is None and LP.param_new("pre", 5) is None and LP.param_new("out_mid", "x:%:a") is None
    and LP.param_new("nope", "a%") is None, "L3 꼴 안 맞음·문자열 아님·모르는 꼴 = 증명 불가(None)")
chk(LP.to_select("  SELECT k FROM meta WHERE k LIKE ?") == ("  SELECT k FROM meta WHERE k LIKE ?", 0), "L3 SELECT 그대로")
chk(LP.to_select("DELETE FROM meta WHERE k LIKE 'a_%'") == ("SELECT rowid FROM meta WHERE k LIKE 'a_%'", 0), "L3 DELETE → SELECT rowid")
chk(LP.to_select("UPDATE meta SET v=?, w=? WHERE k LIKE ?") == ("SELECT rowid FROM meta WHERE k LIKE ?", 2), "L3 UPDATE → SET 의 '?' 2개 뺌")
chk(LP.to_select("INSERT INTO t(a) SELECT k FROM meta WHERE k LIKE ?") == ("SELECT k FROM meta WHERE k LIKE ?", 0), "L3 INSERT…SELECT")
chk(LP.to_select("INSERT INTO t(a) VALUES (?)") is None and LP.to_select("PRAGMA x") is None, "L3 그 밖 = None(증명 불가)")
chk(LP.to_select("WITH c AS (SELECT 1) SELECT k FROM meta WHERE k LIKE ?") is not None
    and LP.to_select("WITH c AS (SELECT 1) DELETE FROM meta WHERE k LIKE 'a_%'") is None, "L3 WITH = 본문 SELECT 만(WITH … DELETE = 증명 불가)")
chk(LP._q_index("SELECT '?' , ? WHERE k LIKE ?", 28) == 1, "L3 따옴표 안 '?' 는 셈 밖")
_qs = 'SELECT k FROM t WHERE "?"=0 AND [c?]=1 AND `d?`=2 AND k LIKE ? AND v=?'
chk(LP._q_index(_qs, _qs.index("LIKE ?") + 5) == 0 and LP._q_index("a='x?''?' AND b=?", 17) == 1,
    "L3 따옴표 식별자(\"…\" · […] · `…`)·'' 이스케이프 안 '?' 도 셈 밖")
chk(LP._named_params("SELECT k FROM t WHERE v=?2 AND k LIKE ?") and LP._named_params("SELECT k FROM t WHERE :flag IS NOT NULL AND k LIKE ?")
    and not LP._named_params("SELECT k FROM t WHERE v=':x?1' AND k LIKE ?")
    and isinstance(LP.rewrite("SELECT k FROM t WHERE v=?2 AND k LIKE ?", ("a", "b", "c%"), []), str),
    "L3 번호·이름 매개변수가 따옴표 밖에 있으면 증명 불가(자리 셈 안 믿음)")

FAKE = '''
def lit_site(conn):
    return conn.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%' ORDER BY k").fetchall()


def pre_site(conn, chain):
    return conn.execute("SELECT k FROM meta WHERE k LIKE ? ORDER BY k", (f"wrecon_done:{chain}:%",)).fetchall()


def twice(conn, chain):
    a = conn.execute("SELECT k FROM meta WHERE k LIKE ?", (f"wrecon_done:{chain}:%",)).fetchall()
    b = conn.execute("SELECT k FROM meta WHERE k LIKE ?", (f"wrecon_tok:{chain}:%",)).fetchall()
    return a, b


def del_site(conn):
    conn.execute("DELETE FROM meta WHERE k LIKE 'ext_prewindow:%'")


def upd_site(conn, v):
    conn.execute("UPDATE meta SET v=? WHERE k LIKE 'x_y:%'", (v,))


def cur_site(conn):
    cur = conn.cursor()
    cur.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%'")
    return cur.fetchall()


def bad_bind(conn):
    return conn.execute("SELECT k FROM meta WHERE v LIKE ?", (123,)).fetchall()


def snap(conn, a, lower):
    q = "SELECT k FROM meta WHERE " + ("lower(v) LIKE ?" if lower else "v LIKE ?")
    return conn.execute(q, (f"%{a}%",)).fetchall()


def two_in_one(conn, chain):
    return conn.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%' OR k LIKE ?", (f"wrecon_done:{chain}:%",)).fetchall()


def inner_plan(conn, chain):
    head = "SELECT k FROM meta WHERE "   # 조립: 피호출자 앵커('k LIKE ? ORDER BY k')가 호출자 전체 SQL 앵커 안에 듦
    return conn.execute(head + "k LIKE ? ORDER BY k", (f"wrecon_done:{chain}:%",)).fetchall()


def outer_plan(conn, chain, delegate):
    if delegate:
        return inner_plan(conn, chain)
    return conn.execute("SELECT k FROM meta WHERE k LIKE ? ORDER BY k", (f"wrecon_done:{chain}:%",)).fetchall()


def case_upd(conn):
    conn.execute("UPDATE meta SET v=CASE WHEN k LIKE 'recon_done_%' THEN 'yes' ELSE 'no' END WHERE 1")


def comment_q(conn):
    return conn.execute("SELECT k FROM meta /* ? */ WHERE k LIKE ? AND v=? ORDER BY k", ("wrecon_done:sol:%", "1")).fetchall()


def never(conn):
    return conn.execute("SELECT k FROM meta WHERE k LIKE 'never_%'").fetchall()
'''
FSRC = os.path.join(T.TMP, "lpsrc")
os.makedirs(FSRC, exist_ok=True)
with open(os.path.join(FSRC, "lpfake.py"), "w", encoding="utf-8") as f:
    f.write(FAKE)
fsites = LP.find_sites(FSRC)
ids = {s["id"]: s for s in fsites}
chk(len(fsites) == 17 and {s["kind"] for s in fsites} == {"lit", "param"}, "L4 합성 자리 17", sorted(ids))
TPL = {"lpfake:pre_site:k": "pre", "lpfake:twice:k": ("pre", "wrecon_done:"), "lpfake:twice:k#2": ("pre", "wrecon_tok:"),
       "lpfake:bad_bind:v": "mid", "lpfake:snap:v": "mid", "lpfake:snap:lower(v)": "mid", "lpfake:two_in_one:k#2": "pre",
       "lpfake:inner_plan:k": "pre", "lpfake:outer_plan:k": "pre", "lpfake:comment_q:k": "pre"}
try:
    proof = LP.Proof(FSRC, fsites, templates=TPL)
    LP.activate(proof)
    sys.path.insert(0, FSRC)
    fake = importlib.import_module("lpfake")
    conn = sqlite3.connect(":memory:", factory=LP.ProofConn)
    conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    rows = [("recon_done_eth", "a_b"), ("reconXdone_eth", "AxB"), ("wrecon_done:eth:w1", "1"), ("wreconXdone:eth:w2", "1"),
            ("wrecon_done:sol:w1", "1"), ("wrecon_tok:sol:t1", "1"), ("ext_prewindow:1", "1"), ("x_y:1", "0"), ("xzy:1", "0")]
    conn.executemany("INSERT INTO meta VALUES (?, ?)", rows)
    plain = sqlite3.connect(":memory:")
    plain.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    plain.executemany("INSERT INTO meta VALUES (?, ?)", rows)
    got_lit = fake.lit_site(conn)
    chk(got_lit == plain.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%' ORDER BY k").fetchall(), "L4 앱 결과 = 감싸개 없는 연결 결과")
    fake.pre_site(conn, "eth")
    fake.pre_site(conn, "sol")
    fake.twice(conn, "sol")
    fake.del_site(conn)
    fake.upd_site(conn, "9")
    fake.cur_site(conn)
    fake.bad_bind(conn)
    fake.snap(conn, "a_b", True)
    fake.two_in_one(conn, "sol")
    fake.outer_plan(conn, "sol", True)
    chk(conn.execute("SELECT count(*) FROM meta WHERE k='ext_prewindow:1'").fetchone()[0] == 0, "L4 DELETE 는 그대로 실행됨")
    chk(conn.execute("SELECT v FROM meta WHERE k='xzy:1'").fetchone()[0] == "9", "L4 UPDATE 는 그대로 실행됨(옛 '_' 와일드카드 그대로)")
    fake.case_upd(conn)
    fake.comment_q(conn)
    rep = proof.report()
    S = rep["sites"]
    chk(S["lpfake:case_upd:k"]["unprovable"] == 1 and S["lpfake:case_upd:k"]["why"] == {"SELECT 꼴에서 LIKE 빠짐": 1},
        "L4 닫힌 쪽: SELECT 꼴에서 그 LIKE 가 빠지면(SET·CASE 안) = 증명 불가(같음 금지)", S["lpfake:case_upd:k"])
    chk(S["lpfake:comment_q:k"]["unprovable"] == 1 and S["lpfake:comment_q:k"]["why"] == {"SQL 에 주석": 1},
        "L4 닫힌 쪽: SQL 에 주석(/* · --) = 증명 불가", S["lpfake:comment_q:k"])
    chk(S["lpfake:lit_site:k"]["state"] == "다름 있음" and S["lpfake:lit_site:k"]["diff"] == 1, "L4 리터럴 '_' 충돌 = 다름", S["lpfake:lit_site:k"])
    chk(S["lpfake:pre_site:k"]["exec"] == 2 and S["lpfake:pre_site:k"]["diff"] == 1 and S["lpfake:pre_site:k"]["same"] == 1
        and S["lpfake:pre_site:k"]["bindings"] == 2, "L4 매개변수: eth 충돌 = 다름 · sol = 같음 · 바인딩 2", S["lpfake:pre_site:k"])
    chk(S["lpfake:twice:k"]["exec"] == 1 and S["lpfake:twice:k#2"]["exec"] == 1, "L4 같은 SQL 두 자리 = 바인딩 머리로 가름",
        [S["lpfake:twice:k"], S["lpfake:twice:k#2"]])
    chk(S["lpfake:del_site:k"]["same"] == 1, "L4 DELETE = SELECT rowid 비교(실행 직전)", S["lpfake:del_site:k"])
    chk(S["lpfake:upd_site:k"]["diff"] == 1, "L4 UPDATE = SET '?' 뺀 SELECT rowid · 'x_y' ↔ 'xzy' 충돌 = 다름", S["lpfake:upd_site:k"])
    chk(S["lpfake:cur_site:k"]["exec"] == 1, "L4 커서(conn.cursor().execute) 길도 셈", S["lpfake:cur_site:k"])
    chk(S["lpfake:bad_bind:v"]["unprovable"] == 1 and S["lpfake:bad_bind:v"]["state"] == "증명 불가 있음", "L4 문자열 아닌 바인딩 = 증명 불가")
    chk(S["lpfake:snap:lower(v)"]["exec"] == 1 and S["lpfake:snap:v"]["exec"] == 0, "L4 더 긴 앵커 안 짧은 앵커 = 셈 밖",
        [S["lpfake:snap:lower(v)"], S["lpfake:snap:v"]])
    chk(S["lpfake:never:k"]["state"] == "실행 안 됨", "L4 부르지 않은 자리 = 실행 안 됨")
    chk(S["lpfake:inner_plan:k"]["exec"] == 1 and S["lpfake:outer_plan:k"]["state"] == "실행 안 됨",
        "L4 호출자·피호출자가 같은 앵커 = execute 에 가까운 함수 자리만(위임한 호출자 자리 = 실행 안 됨)",
        [S["lpfake:inner_plan:k"], S["lpfake:outer_plan:k"]])
    chk(any("two_in_one" in k and v["exec"] == 1 for k, v in rep["statements"].items()), "L4 한 문장 두 자리 = 문장 비교", rep["statements"])
    chk(rep["totals"]["실행 안 됨"] >= 1 and rep["totals"]["다름 있음"] >= 2, "L4 합계", rep["totals"])
    cap = LP.Proof(FSRC, fsites, max_checks=1, templates=TPL)
    LP.activate(cap)
    fake.pre_site(conn, "sol")
    fake.pre_site(conn, "sol")
    cs = cap.report()["sites"]["lpfake:pre_site:k"]
    chk(cs["exec"] == 2 and cs["checked"] == 1 and cs["state"] == "표본 같음(--max-checks)", "L4 상한(--max-checks) 넘은 실행 = '같음'이 아니라 표본", cs)
    LP.activate(None)
    fake.lit_site(conn)
    chk(proof.report()["sites"]["lpfake:lit_site:k"]["exec"] == 1, "L4 끄면(activate None) 안 셈")
    conn.close()
    plain.close()
finally:
    LP.activate(None)

chk(LP.verdict([(1,), (2,)], [(1,), (2,)]) == "같음", "L5 같음")
chk(LP.verdict([(1,), (2,)], [(2,), (1,)]) == "순서", "L5 순서만 다름")
chk(LP.verdict([(1,), (1,)], [(1,)]) == "다름", "L5 중복 수 다름 = 다름")


def _exits(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    return False


chk(_exits(LP._out_path, os.path.join(T.TMP, "x.json")), "L6 출력 = ~/tj_golden/out 밖 거부")
chk(_exits(LP._out_path, os.path.join(LP.OUT_DIR, "sub", "x.json")), "L6 출력 = out 아래 하위 폴더 거부")
chk(not _exits(LP._out_path, os.path.join(LP.OUT_DIR, "like_proof_t.json")), "L6 출력 = out 바로 아래 like_* 허용(파일은 안 만듦)")
chk(all(_exits(LP._out_path, os.path.join(LP.OUT_DIR, n)) for n in ("base_s7.json", "gate7_x.sum", "replay_x.json", "like_proof_t.txt")),
    "L6 출력 = like_*.json|log 밖 이름(기준 base_s7 등) 거부")
chk(LP.Proof(FSRC, fsites, max_checks=-1).max_checks == 0, "L6 음수 비교 상한 = 0(전부 비교)")
chk(all(_exits(LP._tag, t) for t in ("ra1", "base0", "Abc", "a.b", "a/b", "")) and not _exits(LP._tag, "s12lp"), "L6 이름표 규칙")
chk(_exits(LP._frozen_base), "L6 run = 동결 사본(.golden_copy) 아닌 TJ_BASE 에서 거부")
ha, hb = os.path.join(T.TMP, "hl_a.txt"), os.path.join(T.TMP, "hl_b.txt")
with open(ha, "w", encoding="utf-8") as f:
    f.write("keep")
os.link(ha, hb)
with LP._open_new(hb) as f:
    f.write("new")
with open(ha, encoding="utf-8") as f:
    chk(f.read() == "keep", "L6 하드링크 출력 자리 = 옛 이름만 지우고 새 파일(다른 이름의 내용 그대로)")
chk(_exits(LP._fresh, T.TMP), "L6 출력 자리에 폴더 = 거부")
cq = sqlite3.connect(":memory:", factory=LP.ProofConn)
cq.execute("CREATE TABLE t (k TEXT)")
try:
    LP.Proof(FSRC, fsites)._q(cq, "INSERT INTO t VALUES ('x')", ())
    wrote = True
except sqlite3.Error:
    wrote = False
chk(not wrote and cq.execute("SELECT count(*) FROM t").fetchone()[0] == 0 and cq.execute("PRAGMA query_only").fetchone()[0] == 0,
    "L6 비교 질의 = 읽기만(query_only · 쓰기 거부 · 끝나면 원래 값)")
cq.close()
probe = os.path.join(T.TMP, "like_probe")
os.makedirs(probe, exist_ok=True)
chk(_exits(LP._rm, probe) and os.path.isdir(probe), "L6 지우기 = 도구 이름표 폴더(runs·shadow 의 like_*) 밖 거부 · 그대로 둠")
chk(_exits(LP._rm, os.path.join(LP.GOLD, "shadow", "ra1")) and _exits(LP._rm, os.path.join(LP.GOLD, "base0")), "L6 기준(ra1·base0) 지우기 거부")
T.finish()
