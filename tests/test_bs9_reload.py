#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import dataclasses  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "bs9_reload.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/bs9_reload.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import bs9_reload as B  # noqa: E402


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


texts, _trees, stages = B.load(T.SRC)
rows = B.plan(stages)
n_rel = sum(len(s.reloads) for s in stages)
acts = {}
for r in rows:
    acts[r["act"]] = acts.get(r["act"], 0) + 1
chk(len(rows) == n_rel and all(r["cls"] in ("dead", "real") for r in rows) and all(r["act"] for r in rows),
    "R1 지금 src 재적재 %d = 죽은 %d + 진짜 %d · 처리 %s" % (n_rel, sum(r["cls"] == "dead" for r in rows), sum(r["cls"] == "real" for r in rows), acts))
TMP = tempfile.mkdtemp(prefix="tj_bs9_")
try:
    cp = os.path.join(TMP, "src")
    shutil.copytree(T.SRC, cp, ignore=shutil.ignore_patterns("__pycache__"))
    rc, out = quiet(B.main, ["--apply", "--src", cp])
    _t2, _tr2, st2 = B.load(cp)
    left = sum(len(s.reloads) for s in st2)
    rows2 = B.plan(st2)
    chk(rc == 0 and left == acts.get("keep", 0) + acts.get("refuse", 0) and not any(r["cls"] == "dead" for r in rows2),
        "R1 임시 사본에 적용 — compile·심볼 표 같음 · 남는 재적재 = 남김 + 거부(%d) · 다시 분석해도 죽은 쌍 0" % left, out[-400:])

    bnd = B.boundary(T.SRC, stages, rows)
    with open(os.path.join(TOOLS, "act5_boundary.json"), encoding="utf-8") as f:
        saved = json.load(f)
    chk(saved.get("boundary") == bnd["boundary"] and saved.get("books_fields") == bnd["books_fields"]
        and saved.get("ctx_fields") == bnd["ctx_fields"] and saved.get("groups") == bnd["groups"],
        "R2 act5_boundary.json = 지금 src 로 다시 뽑은 경계(%d · Books %d · ctx %d)" % (
            len(bnd["boundary"]), len(bnd["books_fields"]), len(bnd["ctx_fields"])),
        {"더해짐": sorted(set(bnd["boundary"]) - set(saved.get("boundary") or [])),
         "빠짐": sorted(set(saved.get("boundary") or []) - set(bnd["boundary"]))})

    import accounting_books as AB  # noqa: E402
    old = AB.ReplayResult.old_names()
    edge = [f.name for f in dataclasses.fields(AB.ReplayResult) if f.name not in ("books", "ctx", "_scope", "_cb")]
    chk(len(old) == len(set(old)) and set(old) == {"books", "ctx"} | set(saved["books_fields"]) | set(saved["boundary"])
        and sorted(AB.OLD.get(f, f) for f in edge) == sorted(set(saved["boundary"]) - set(saved["books_fields"]))
        and set(AB.OLD) <= set(edge) and all(AB.OLD[f] != f for f in AB.OLD)
        and not [f for f in edge if f.startswith("_") or f.endswith("9")],
        "R6 ReplayResult 옛 이름 = books·ctx + Books 필드 + 경계(%d) · 경계 필드 %d(끝 9·앞 밑줄 없음 · OLD %d)" % (len(old), len(edge), len(AB.OLD)),
        {"더해짐": sorted(set(old) - {"books", "ctx"} - set(saved["books_fields"]) - set(saved["boundary"])),
         "빠짐": sorted(set(saved["boundary"]) - set(old))})
    never = []
    for n in sorted(set(saved["boundary"]) | {"books", "ctx"}):
        p9, between = B.always_present(stages, B.N_REPLAY, n)
        if p9 is None or not p9.replay or between:
            never.append((n, p9.name if p9 else None, between))
    chk(not never, "R6 경계 이름 = 리플레이 단계가 늘 묶음(사이 pop 없음 · from_scope 가 KeyError 로 막는 길 없음)", never[:10])

    syn = os.path.join(TMP, "syn")
    os.makedirs(syn)
    UPD = '        _bs9.update((k9, v9) for k9, v9 in locals().items() if k9 != "_bs9")\n'
    mods = {
        "accounting_books": "from dataclasses import dataclass\n\n\n@dataclass\nclass Books:\n    tax_rows: list = None\n",
        "accounting_ctx": "from dataclasses import dataclass\n\n\n@dataclass\nclass ReplayCtx:\n    now: float = 0.0\n",
        "view_b_replay": (
            "class ReplayMixin:\n"
            "    def _build_replay(self, conn):\n"
            "        _bs9 = self._replay_prep(conn)\n"
            "        self._replay_main(_bs9)\n        rr = accounting_books.ReplayResult.from_scope(_bs9)\n        return rr\n\n"
            "    def _replay_prep(self, conn):\n        books = 1\n        ctx = 2\n        G = {}\n        a = 5\n        for r in conn:\n            pass\n"
            "        return dict(locals())\n\n"
            "    def _replay_main(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n"
            "        if \"r\" in _bs9:\n            r = _bs9[\"r\"]\n"
            "        if \"ln9\" in _bs9:\n            ln9 = _bs9[\"ln9\"]\n"
            "        if \"k9\" in _bs9:\n            k9 = _bs9[\"k9\"]\n"
            "        def _h():\n            return r\n"
            "        def _g():\n            nonlocal ln9\n            ln9 = 3\n            return ln9\n"
            "        def _f():\n            nonlocal k9\n            print(k9)\n            k9 = 1\n" + UPD),
        "view_b_cards": (
            "class CardsMixin:\n    def _build_cards(self, _bs9):\n        (G, a,) = (_bs9[\"G\"], _bs9[\"a\"],)\n"
            "        global gq\n        if \"q\" in _bs9:\n            q = _bs9[\"q\"]\n        if \"gq\" in _bs9:\n            gq = _bs9[\"gq\"]\n"
            "        q = len(G)\n        print(q)\n" + UPD),
        "view_b_pendings": ("class PendingsMixin:\n    def _build_pendings(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n"
                            "        if \"z\" in _bs9:\n            z = _bs9[\"z\"]\n        z = 1\n        print(vars(), z)\n" + UPD),
        "view_b_outflows": ("class OutflowsBuildMixin:\n    def _build_outflows(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n"
                            "        if \"a\" in _bs9:\n            a = _bs9[\"a\"]\n        print(a)\n" + UPD),
        "view_b_daily": ("class DailyBuildMixin:\n    def _build_daily(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n"
                         "        if \"ex9\" in _bs9:\n            ex9 = _bs9[\"ex9\"]\n        try:\n            pass\n"
                         "        except ValueError as ex9:\n            print(ex9)\n        d = _bs9.get(\"dep_tr9\")\n" + UPD),
        "view_b_futidx": ("class FutIdxMixin:\n    def _build_futidx(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n"
                          "        if \"xx\" in _bs9:\n            xx = _bs9[\"xx\"]\n        G[xx] += 1\n" + UPD),
        "view_b_tail": "class TailMixin:\n    def _build_tail(self, _bs9):\n        (G,) = (_bs9[\"G\"],)\n        return {\"fields\": G}\n",
        "view_builder": ("class StateBuilder:\n    def _build(self, conn):\n        rr = self._build_replay(conn)\n"
                         "        _bs9 = rr.screen_scope(1)\n        self._build_cards(_bs9)\n        return self._build_tail(_bs9)\n"),
    }
    for m, txt in mods.items():
        with open(os.path.join(syn, m + ".py"), "w", encoding="utf-8") as f:
            f.write(txt)
    s_texts, _st, s_stages = B.load(syn)
    s_rows = B.plan(s_stages)
    got = {(r["stage"], r["name"]): r["act"] for r in s_rows}
    want = {
            ("_replay_main", "r"): "keep", ("_replay_main", "ln9"): "declare", ("_replay_main", "k9"): "keep",
            ("_build_cards", "q"): "delete", ("_build_cards", "gq"): "refuse", ("_build_pendings", "z"): "refuse",
            ("_build_outflows", "a"): "head", ("_build_daily", "ex9"): "delete", ("_build_futidx", "xx"): "keep"}
    chk(got == want, "R3 합성 단계 처리(죽음 지움 · 처리기 이름 · 유일 바인딩 선언 · 머리 풀기 · 남김 · nonlocal 흐름 · pop·global·vars 거부)",
        {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v})
    new = B.apply_plan(s_texts, s_stages, s_rows)
    links_head = [ln for ln in new["view_b_outflows"].splitlines() if "(G, a," in ln]
    chk(links_head == ['        (G, a,) = (_bs9["G"], _bs9["a"],)'] and "        ln9: object" in new["view_b_replay"].splitlines()
        and new["view_b_outflows"].count('_bs9["a"]') == 1 and 'if "ex9" in _bs9' not in new["view_b_daily"],
        "R3 적용 글 — 머리 풀기 같은 줄 끝에 더함 · 값 없는 선언 한 줄 · 거부·남김은 그대로", links_head)

    forced = [dict(r, act="delete") if (r["stage"], r["name"]) == ("_replay_main", "ln9") else r for r in s_rows]
    try:
        B.apply_plan(s_texts, s_stages, forced)
        refused = ""
    except B.Refuse as e:
        refused = str(e)
    chk("view_b_replay" in refused, "R4 유일 바인딩을 억지로 지우면 적용 거부(compile·심볼 표 검증)", refused)

    ref0 = os.environ.get("TJ_TEST_ARCH_BASE_REF") or "refactor"
    if ref0.lower() in ("none", "skip", "-", "0", "off") or shutil.which("git") is None or subprocess.run(
            ["git", "-C", T.ROOT, "rev-parse", "--verify", "-q", ref0], capture_output=True).returncode != 0:
        ref0 = "none"
    rc0, out0 = quiet(B.run_check, T.SRC, ref0)
    chk(rc0 == 0, "R5 --check 지금 트리 위반 0(위치 문자열 기준 %s)" % ref0, out0[-600:])
    if shutil.which("git") is None:
        chk(True, "R5 git 없음 — 위치 문자열 검사 합성 건너뜀")
    else:
        repo = os.path.join(TMP, "repo")
        shutil.copytree(syn, os.path.join(repo, "src"))
        with open(os.path.join(repo, "src", "view_b_futidx.py"), "a", encoding="utf-8") as f:
            f.write("\n\ndef _cg(e):\n    calcguard.swallowed(\"view_b_futidx:x[a]\", e)\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for cmd in (["init", "-q", "-b", "refactor"], ["add", "-A"], ["commit", "-q", "-m", "x"], ["checkout", "-q", "-b", "work"]):
            subprocess.run(["git", "-C", repo] + cmd, check=True, env=env, capture_output=True)
        src2 = os.path.join(repo, "src")
        p = os.path.join(src2, "view_b_futidx.py")
        txt = open(p, encoding="utf-8").read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt.replace("view_b_futidx:x[a]", "view_b_futidx:x[b]").replace(
                '(G,) = (_bs9["G"],)', '(G, H) = (_bs9["G"], _bs9["G2"])\n        w = _bs9["zz"]\n        v = _bs9.get("zz")\n'
                '        if "zz" in _bs9:\n            print(1)'))
        rc1, out1 = quiet(B.run_check, src2, "refactor")
        chk(rc1 == 5 and "재적재 꼴이 아님" in out1 and "calcguard 위치 문자열 view_b_futidx.py: 더해짐 ['view_b_futidx:x[b]'] · 빠짐 ['view_b_futidx:x[a]']" in out1 and "머리 풀기 H ← G2" in out1
            and "_build_futidx(load) zz" in out1 and "_build_futidx(get) zz" in out1,
            "R5 --check 합성 위반(위치 문자열 바뀜 · 머리 풀기 이름 ≠ 열쇠 · 새 첨자 · 새 .get · 재적재 아닌 열쇠 있음 검사)을 잡음", out1[-900:])
    import ast  # noqa: E402
    ct = os.path.join(T.ROOT, "public", "tests", "test_build_stage_contract.py")
    lit = [ast.literal_eval(n.value) for n in ast.parse(open(ct, encoding="utf-8").read()).body
           if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "ALLOWED" for t in n.targets)]
    chk(os.path.realpath(B.CONTRACT_TEST) == os.path.realpath(ct) and lit == [B.ALLOWED] and B.ALLOWED,
        "R7 도구 ALLOWED = 공개 시험 test_build_stage_contract.ALLOWED(한 벌 · 도구 위치 기준 경로)", {"tool": str(B.CONTRACT_TEST), "test": ct})
    bad_rej = []
    for i, body in enumerate(('ALLOWED = {("a", "b", "get", "k"): 1}\nALLOWED = {}\n', 'ALLOWED = dict(x=1)\n',
                              'ALLOWED = {("a", "b", "get", "k"): 0}\n', 'ALLOWED = {("a", "b", "k"): 1}\n', 'X = 1\n')):
        fp = os.path.join(TMP, "allowed_%d.py" % i)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(body)
        try:
            B.load_allowed(fp)
            bad_rej.append(body)
        except (RuntimeError, ValueError):
            pass
    chk(not bad_rej, "R7 정본 모양 틀림(대입 2개 · 리터럴 아님 · 값 0 · 열쇠 3칸 · 대입 없음) = 거부", bad_rej)
finally:
    shutil.rmtree(TMP, ignore_errors=True)
T.finish()
