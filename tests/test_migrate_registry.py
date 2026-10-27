#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

import core  # noqa: E402
import core_svc  # noqa: E402
import db  # noqa: E402
import migrate  # noqa: E402

chk = T.chk
KINDS = ("스키마 확장", "데이터 1회", "시드 1회", "세대 1회")
REG = migrate.REGISTRY
TOOLS = os.path.join(T.ROOT, "tools")
HAVE_TOOLS = os.path.isfile(os.path.join(TOOLS, "rebuild2.py"))
MIG_FILE = re.compile(r"^mig_(\d{4})_([a-z0-9_]+)\.py$")


def key_pat(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
    return None


def reg_pat(stamp):
    return re.sub(r"<[^>]*>", "*", stamp)


_W_SQL = re.compile(r"^\s*(?:INSERT\s+OR\s+REPLACE|REPLACE|INSERT)\s+INTO\s+meta\b", re.I)
_W_LIT = re.compile(r"VALUES\s*\(\s*'([^']+)'", re.I)
_R_SQL = re.compile(r"^\s*SELECT\b.*\bFROM\s+meta\b.*\bk\s*=\s*(?:'([^']+)'|\?)", re.I | re.S)


def _first_param(call):
    if len(call.args) > 1 and isinstance(call.args[1], (ast.Tuple, ast.List)) and call.args[1].elts:
        return key_pat(call.args[1].elts[0])
    return None


def meta_key(call, rx):
    sql = key_pat(call.args[0]) if call.args else None
    if sql is None or not rx.match(sql):
        return None
    lit = (_W_LIT.search(sql) if rx is _W_SQL else rx.match(sql))
    if lit and lit.group(1):
        return lit.group(1)
    return _first_param(call)


def stamp_funcs(src_dir):
    out = {}
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(src_dir, fn), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        def walk(node, path, mod=fn[:-3]):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.ClassDef):
                    walk(ch, path + [ch.name])
                elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    reads, writes = set(), set()
                    for n in ast.walk(ch):
                        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                            continue
                        if n.func.attr == "_meta_get" and n.args and key_pat(n.args[0]) is not None:
                            reads.add(key_pat(n.args[0]))
                        elif n.func.attr == "execute":
                            writes.add(meta_key(n, _W_SQL))
                            reads.add(meta_key(n, _R_SQL))
                    both = (reads & writes) - {None}
                    if both:
                        out[(mod, ".".join(path + [ch.name]))] = both
        walk(tree, [])
    return out


def call_sites(roots, names):
    out = {n: [] for n in names}
    for prefix, d in roots:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            mod = prefix + fn[:-3]

            def walk(node, path):
                for ch in ast.iter_child_nodes(node):
                    if isinstance(ch, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        walk(ch, path + [ch.name])
                    else:
                        if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute) and ch.func.attr in out:
                            out[ch.func.attr].append(".".join([mod] + path))
                        walk(ch, path)
            walk(tree, [])
    return {k: sorted(set(v)) for k, v in out.items()}


def func_calls(src_dir, attr):
    out = {}
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(src_dir, fn), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        def walk(node, path):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.ClassDef):
                    walk(ch, path + [ch.name])
                elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for n in ast.walk(ch):
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr and len(n.args) > 1:
                            a = n.args[1]
                            out.setdefault(".".join([fn[:-3]] + path + [ch.name]), []).append(a.value if isinstance(a, ast.Constant) else None)
        walk(tree, [])
    return out


def mig_problems(src_dir, reg):
    bad = []
    files = sorted(f for f in os.listdir(src_dir) if f.startswith("mig_") and f.endswith(".py"))
    by_where = {m.where: m for m in reg}
    for f in files:
        m = MIG_FILE.match(f)
        if not m:
            bad.append("이름 꼴 mig_NNNN_<이름>.py 아님: " + f)
            continue
        with open(os.path.join(src_dir, f), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        if not any(isinstance(n, ast.FunctionDef) and n.name == "run" and len(n.args.args) == 1 for n in tree.body):
            bad.append("run(core) 없음: " + f)
        e = by_where.get(f[:-3] + ".run")
        if e is None or e.n != int(m.group(1)):
            bad.append("등록부 줄 없음(번호 %s · 정의 %s.run): %s" % (m.group(1), f[:-3], f))
    for e in reg:
        if e.where.startswith("mig_") and e.where[:-4] + ".py" not in files:
            bad.append("등록부 줄의 파일 없음: " + e.where)
    return bad


STATE = {
    ("core_exf", "ExfMixin._exf_ext_settling"): "거래소별 정착 표식(대사마다 갱신 · 원장 변환 아님)",
    ("core_exf", "ExfMixin._exf_shrink"): "되돌림 기록 실패 표식(경고용 상태)",
    ("core_exf", "ExfMixin.exf_recon_pass"): "해외 대사 표식·선물 떼기 시작·부채 표식(대사마다 갱신 · 등록부 4·5·6·8 을 부르는 자리)",
    ("core_fills", "FillsMixin._consume_exf_retime_cached"): "빗썸 체결 시각 바로잡기 요청 처리 캐시(요청 레코드마다)",
    ("core_recon", "ReconMixin._recon_pass_scopes"): "체인별 대사 완료 표식(대사 상태 · 등록부 7 이 지우는 열쇠)",
    ("core_upbit_recon", "UpbitReconMixin.exchange_recon_pass"): "업비트 대사 완료 표식(대사 상태)",
    ("search_index", "Index.open"): "검색 색인(원장과 다른 DB 파일)의 판 표식",
}


def registry_problems(src_dir, reg, sites=None, state=None):
    bad = []
    state = STATE if state is None else state
    got = stamp_funcs(src_dir)
    want = {(e.where.split(".", 1)[0], e.where.split(".", 1)[1]): reg_pat(e.stamp) for e in reg if e.n}
    for k, pats in sorted(got.items()):
        if k in state:
            continue
        if k not in want:
            bad.append("등록부 밖 도장 함수 %s.%s %s" % (k[0], k[1], sorted(pats)))
        elif want[k] not in pats:
            bad.append("도장 무늬 다름 %s.%s 등록부 %s · 코드 %s" % (k[0], k[1], want[k], sorted(pats)))
    for k in sorted(set(want) - set(got)):
        bad.append("등록부 줄의 도장 함수 없음 %s.%s" % k)
    if sites is not None:
        for e in reg:
            if not e.n:
                continue
            have = sites.get(e.name, [])
            exp = sorted(c for c in e.callers if HAVE_TOOLS or not c.startswith("tools/"))
            if have != exp:
                bad.append("부르는 자리 다름 %s 등록부 %s · 코드 %s" % (e.name, exp, have))
    return bad + mig_problems(src_dir, reg)


shape = []
if [e.n for e in REG] != list(range(len(REG))) or len(REG) != 10:
    shape.append("번호 0~9 연속 아님")
if len({e.name for e in REG}) != len(REG):
    shape.append("이름 겹침")
shape += ["종류 %s: %s" % (e.name, e.kind) for e in REG if e.kind not in KINDS]
shape += ["startup 줄 칸 %s" % e.name for e in REG if ("migrate.startup" in e.callers) != bool(e.guard and e.fail_log)]
e0 = REG[0]
if (e0.kind, e0.where, e0.callers, e0.data_rev) != ("스키마 확장", "db.DDL", ("db.open_db",), 0):
    shape.append("0 = 기준 스키마 칸")
shape += ["빈 칸 %s" % e.name for e in REG if not (e.stamp and e.where and e.callers and e.again and e.rebuild)]
chk(not shape, "R1 등록부 모양(번호 0~9 · 이름 고유 · 종류 4종 · 0 = 기준 스키마 · startup 줄만 위치 글·로그 글 · 빈 칸 0)", shape)

ddl_bad = [s.split("(")[0][:60] for s in db.DDL
           if not re.match(r"^\s*(?:PRAGMA\b|CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER)\s+IF\s+NOT\s+EXISTS\b)", s, re.I)
           or re.search(r"\b(?:ALTER|DROP)\s+(?:TABLE|INDEX|TRIGGER)\b", s, re.I)]
chk(db.SCHEMA_VERSION == core.Core.LEDGER_GEN and not ddl_bad,
    "R2 db.SCHEMA_VERSION = Core.LEDGER_GEN · DDL = PRAGMA·CREATE … IF NOT EXISTS 만(ALTER·DROP 0)", (db.SCHEMA_VERSION, ddl_bad))
revs = [e.data_rev for e in REG if e.data_rev]
chk(all(1 <= r <= db.DATA_REV and r in db.DATA_REVS for r in revs) and len(set(revs)) == len(revs),
    "R2 등록부 data_rev ≤ db.DATA_REV · db.DATA_REVS 에 있음 · 번호 겹침 0", revs)

roots = [("", T.SRC)] + ([("tools/", TOOLS)] if HAVE_TOOLS else [])
sites = call_sites(roots, [e.name for e in REG if e.n])
got = stamp_funcs(T.SRC)
chk(len(got) == 16 and len(set(got) - set(STATE)) == 9 and set(STATE) <= set(got),
    "R3 같은 meta 열쇠를 읽고 쓰는 src 함수 16 = 1회 변환 9(세션32 자동 처리 칸 영수증 포함) + 상태 열쇠 7(닫힌 표 · 엔진이 비지 않음 · 표 줄이 다 쓰임)", sorted(got))
probs = registry_problems(T.SRC, REG, sites)
chk(not probs, "R3·R4 등록부 = 도장 함수(정의 자리·도장 무늬) · 부르는 자리(src%s)" % ("·tools" if HAVE_TOOLS else " — 공개판 배치: tools 건너뜀"), probs)
bumps = func_calls(T.SRC, "bump_data_rev")
want_b = {e.where: [e.data_rev] for e in REG if e.data_rev}
chk({k: v for k, v in bumps.items() if k.split(".", 1)[0] != "db"} == want_b, "R4 db.bump_data_rev 부르는 함수 = 등록부 data_rev 줄(번호 같음)", bumps)

with open(os.path.join(T.SRC, "migrate.py"), encoding="utf-8") as fh:
    mt = ast.parse(fh.read())
fn = next(n for n in mt.body if isinstance(n, ast.FunctionDef) and n.name == "startup")
loop = next(n for n in fn.body if isinstance(n, ast.For))
table = []
for el in loop.iter.elts:
    num, lam = el.elts
    chain, node = [], lam.body.func
    while isinstance(node, ast.Attribute):
        chain.insert(0, node.attr)
        node = node.value
    table.append((num.value, node.id if isinstance(node, ast.Name) else None, chain, lam.body.args))
want_st = [e.n for e in REG if "migrate.startup" in e.callers]
st_bad = [(n, root, ch) for n, root, ch, args in table if root != "core" or args or ch[-1] != REG[n].name]
chk([t[0] for t in table] == list(migrate.STARTUP) == want_st == [1, 2, 3] and not st_bad,
    "R5 startup 부르기 표 번호 = STARTUP = 등록부 차례(1·2·3) · 부르기 = core.<등록부 이름>() 하나씩", (table, st_bad))
SVC = [getattr(core_svc, n) for n in core_svc.__all__ if isinstance(getattr(core_svc, n), type)]
miss = [ch for _n, _r, ch, _a in table if not (len(ch) == 1 and ch[0] in dir(core.Core)
                                                or len(ch) == 2 and ch[0].startswith("svc_") and any(ch[1] in dir(k) for k in SVC))]
chk(not miss, "R5 부르기 속성 사슬이 Core 에 있음(서비스로 옮긴 뒤엔 svc_<묶음>.<이름> — 서비스 클래스에 있음)", miss)
lit = {}
for f9 in sorted(os.listdir(T.SRC)):
    if f9.endswith(".py"):
        with open(os.path.join(T.SRC, f9), encoding="utf-8") as fh:
            for n in ast.walk(ast.parse(fh.read())):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "swallowed" and n.args \
                        and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    lit.setdefault(n.args[0].value, []).append(f9)
g_bad = [e.name for e in REG if e.guard and (e.guard != "core:Core.run[%s]" % e.name or e.guard in lit)]
chk(len(lit) > 300 and not g_bad, "R5 위치 글 = core:Core.run[<이름>] · src 의 다른 calcguard.swallowed 글자와 안 겹침", g_bad)
with open(os.path.join(T.SRC, "core.py"), encoding="utf-8") as fh:
    ct = ast.parse(fh.read())
run = next(m for c in ct.body if isinstance(c, ast.ClassDef) and c.name == "Core" for m in c.body
           if isinstance(m, ast.FunctionDef) and m.name == "run")
seq = []
for st in run.body:
    for n in ast.walk(st):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "startup" and isinstance(n.func.value, ast.Name) and n.func.value.id == "migrate":
                seq.append(("startup", [a.id if isinstance(a, ast.Name) else None for a in n.args]))
            elif n.func.attr == "_stable_regroup":
                seq.append(("regroup", []))
    if isinstance(st, ast.While):
        seq.append(("loop", []))
        break
chk(seq == [("regroup", []), ("startup", ["self"]), ("loop", [])],
    "R5 Core.run = 스테이블 재그룹 → migrate.startup(self) 한 번 → 소비 루프(첫 소비 전)", seq)

chk(not mig_problems(T.SRC, REG), "R6 src/mig_*.py = 이름 꼴 · run(core) · 등록부 줄(그 역도)", mig_problems(T.SRC, REG))

SYN = os.path.join(T.TMP, "syn_src")
os.makedirs(SYN, exist_ok=True)


def syn(files):
    for f in os.listdir(SYN):
        os.remove(os.path.join(SYN, f))
    for name, body in files.items():
        with open(os.path.join(SYN, name), "w", encoding="utf-8") as fh:
            fh.write(body)


A = ("class A:\n"
     "    def a_once(self):\n"
     "        if self._meta_get('a_done'):\n            return\n"
     "        self.conn.execute(\"INSERT OR REPLACE INTO meta (k, v) VALUES ('a_done', ?)\", ('1',))\n"
     "    def b_once(self, c):\n"
     "        if self._meta_get(f'b_{c}'):\n            return\n"
     "        self.conn.execute('INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)', (f'b_{c}', '1'))\n"
     "    def go(self):\n        self.a_once()\n        self.b_once(1)\n")
REG_A = (migrate.Migration(0, "기준", "스키마 확장", "schema_version", "db.DDL", ("db.open_db",), "x", 0, "x"),
         migrate.Migration(1, "a_once", "데이터 1회", "a_done", "m.A.a_once", ("m.A.go",), "x", 0, "x"),
         migrate.Migration(2, "b_once", "데이터 1회", "b_<c>", "m.A.b_once", ("m.A.go",), "x", 0, "x"))


def syn_bad(files, reg):
    syn(files)
    return registry_problems(SYN, reg, call_sites([("", SYN)], [e.name for e in reg if e.n]), state={})


ok0 = syn_bad({"m.py": A}, REG_A)
case = {
    "등록부 밖 도장 함수": syn_bad({"m.py": A}, REG_A[:2]),
    "도장 무늬 다름": syn_bad({"m.py": A}, REG_A[:2] + (REG_A[2]._replace(stamp="b_x"),)),
    "부르는 자리 하나 더": syn_bad({"m.py": A + "def h(x):\n    x.a_once()\n"}, REG_A),
    "등록 안 된 mig 파일": syn_bad({"m.py": A, "mig_0003_c.py": "def run(core):\n    pass\n"}, REG_A),
    "이름 틀린 mig 파일": syn_bad({"m.py": A, "mig_3_c.py": "def run(core):\n    pass\n"}, REG_A),
    "run 없는 mig 파일": syn_bad({"m.py": A, "mig_0003_c.py": "def go(core):\n    pass\n"},
                             REG_A + (migrate.Migration(3, "c", "데이터 1회", "c", "mig_0003_c.run", ("migrate.startup",), "x", 0, "x"),)),
}
MIG_OK = ("def run(core):\n    if core._meta_get('c_done'):\n        return\n"
          "    core.conn.execute(\"INSERT OR REPLACE INTO meta (k, v) VALUES ('c_done', ?)\", ('1',))\n")
ok3 = syn_bad({"m.py": A, "mig_0003_c.py": MIG_OK},
              REG_A + (migrate.Migration(3, "c", "데이터 1회", "c_done", "mig_0003_c.run", (), "x", 0, "x"),))
chk(not ok0, "R7 자체: 합성 등록부 = 합성 코드 → 문제 0", ok0)
chk(all(case.values()), "R7 자체: 반례 6 각각 잡힘(%s)" % " · ".join(case), {k: v[:2] for k, v in case.items()})
chk(not ok3, "R7 자체: 등록부 줄 있는 mig_0003_c.py(run(core) · 도장 읽고 씀) = 문제 0", ok3)

T.finish()
