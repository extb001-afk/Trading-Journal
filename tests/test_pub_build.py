#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
PK = os.path.join(T.ROOT, "tools", "package")
if not os.path.isfile(os.path.join(PK, "pub_build.py")):
    public_layout = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(public_layout, "공개판 배치 — 비공개 도구(tools/package/pub_build.py) 없음 · 건너뜀" if public_layout
        else "저장소 배치인데 tools/package/pub_build.py 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, PK)
import pub_build as B  # noqa: E402

ROOT = os.path.realpath(T.ROOT)

p = B.plan(ROOT)
chk(p["errors"] == [] and len(p["files"]) > 1000, f"[1] 공개 목록 {len(p['files'])}파일 · 막는 오류 0", p["errors"][:10])
chk(B.source_checks(ROOT) == [], "[1] 원천 검사 0(공개판 패치 없이 원천 = 공개판 값)", B.source_checks(ROOT))
chk(not any(s9.startswith(("tools/package/", "tools/refactor/")) for s9 in p["files"]) and ".gitignore" not in p["files"].values(),
    "[1] 빌드 도구 자신·내부 도구는 목록 밖 · .gitignore 는 생성 파일")

OUT = os.path.join(os.path.realpath(T.TMP), "pubout")
B.copy_tree(ROOT, OUT, p["files"])
chk(B.verify(ROOT, OUT, p["files"]) == [], "[2] 빌드 직후 원본 그대로 검사 0")
with open(os.path.join(OUT, ".gitignore"), "rb") as f:
    chk(f.read() == B.GITIGNORE.encode("utf-8") and b"\n.env\n" in b"\n" + B.GITIGNORE.encode("utf-8") and b"!.env.example" in B.GITIGNORE.encode(),
        "[2] .gitignore = 정해진 글(.env · config.json · state/ 막음 · 예시는 허용)")
modes = {d9: os.stat(os.path.join(OUT, d9)).st_mode & 0o777 for d9 in p["files"].values()}
chk(all((m == 0o755) == (d9.startswith("tools/") and d9.endswith(".sh")) for d9, m in modes.items()) and modes.get("tools/setup.sh") == 0o755,
    "[2] 실행 비트 = tools/*.sh 만", sorted(d9 for d9, m in modes.items() if m == 0o755))
chk(modes.get("README.md") is not None and os.path.isfile(os.path.join(OUT, "docs", "SCREENS.md"))
    and os.path.isfile(os.path.join(OUT, "web", "v2", "tjdom.js")), "[2] README · docs 7 · 화면 파일 실림")

f_ver = os.path.join(OUT, "VERSION")
with open(f_ver, "rb") as f:
    keep = f.read()
with open(f_ver, "ab") as f:
    f.write(b"x")
chk(B.verify(ROOT, OUT, p["files"]) == ["원본과 바이트 다름: VERSION"], "[3] 바이트 바뀜", B.verify(ROOT, OUT, p["files"]))
with open(f_ver, "wb") as f:
    f.write(keep)
with open(os.path.join(OUT, "src", "zz_extra.py"), "w") as f:
    f.write("x = 1\n")
chk(B.verify(ROOT, OUT, p["files"]) == ["목록에 없는 파일: src/zz_extra.py"], "[3] 목록 밖 파일", B.verify(ROOT, OUT, p["files"]))
os.remove(os.path.join(OUT, "src", "zz_extra.py"))
os.rename(os.path.join(OUT, "LICENSE"), os.path.join(T.TMP, "LICENSE_keep"))
chk(B.verify(ROOT, OUT, p["files"]) == ["빠진 파일: LICENSE"], "[3] 빠진 파일", B.verify(ROOT, OUT, p["files"]))
os.rename(os.path.join(T.TMP, "LICENSE_keep"), os.path.join(OUT, "LICENSE"))
os.symlink(os.path.join(ROOT, "VERSION"), os.path.join(OUT, "docs", "lnk"))
chk(B.verify(ROOT, OUT, p["files"]) == ["심볼릭 링크: docs/lnk"], "[3] 심볼릭 링크", B.verify(ROOT, OUT, p["files"]))
os.remove(os.path.join(OUT, "docs", "lnk"))
with open(os.path.join(OUT, ".gitignore"), "a") as f:
    f.write("!config.json\n")
chk(B.verify(ROOT, OUT, p["files"]) == ["원본과 바이트 다름: .gitignore"], "[3] .gitignore 글 바뀜", B.verify(ROOT, OUT, p["files"]))
with open(os.path.join(OUT, ".gitignore"), "w") as f:
    f.write(B.GITIGNORE)
chk(B.verify(ROOT, OUT, p["files"]) == [], "[3] 되돌리면 다시 0")

chk(B._out_ok(ROOT, "rel/x", True) and B._out_ok(ROOT, os.path.join(ROOT, "dist"), True) and B._out_ok(ROOT, "/", True)
    and B._out_ok(ROOT, OUT, True) and B._out_ok(ROOT, os.path.dirname(ROOT), True), "[4] 상대 · 트리 안 · '/' · 비어 있지 않음 · 트리를 품은 폴더 = 거부")
chk(B._out_ok(ROOT, os.path.join(T.TMP, "fresh_out"), True) == "" and B._out_ok(ROOT, OUT, False) == "", "[4] 새 폴더(build) · 있는 폴더(verify) = 허용")

SR = os.path.join(T.TMP, "srcroot")
for rel in ("src/review_daily.py", "src/review_prompt.py", "src/http_assets.py", "src/brokers/README.md", "web/v2/app.js", "config.example.json"):
    os.makedirs(os.path.dirname(os.path.join(SR, rel)), exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, rel), os.path.join(SR, rel))
for fn in os.listdir(os.path.join(ROOT, "web", "v2")):
    if fn.startswith("tab_") and fn.endswith(".js"):
        shutil.copyfile(os.path.join(ROOT, "web", "v2", fn), os.path.join(SR, "web", "v2", fn))
chk(B.source_checks(SR) == [], "[5] 합성 뿌리(원천 사본) = 0")


def mutate(rel, old, new, want):
    path = os.path.join(SR, rel)
    with open(path, encoding="utf-8") as f:
        s = f.read()
    if old not in s:
        chk(False, f"[5] 변이 대상 없음 {rel}: {old[:40]}")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(s.replace(old, new, 1))
    got = B.source_checks(SR)
    chk(len(got) == 1 and want in got[0], f"[5] 변이 잡음 — {want}", got)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


mutate("src/review_daily.py", 'DCA_NOTE = "같은 몇 분 안 여러 곳 소액 매수 묶음"', 'DCA_NOTE = "합성 개인 메모"', "small_dca")
mutate("src/review_prompt.py", "DEFAULT_KNOWN_PATTERNS = [", 'DEFAULT_KNOWN_PATTERNS = ["합성 운용 패턴", ', "DEFAULT_KNOWN_PATTERNS")
mutate("src/http_assets.py", 'UI_DEFAULT = "v2"', 'UI_DEFAULT = "classic"', "UI_DEFAULT")
RA, TR = "remote" + "_auth", "TJ" + "Remote"
mutate("src/http_assets.py", 'UI_DEFAULT = "v2"', 'UI_DEFAULT = "v2"\nimport ' + RA, "되살아남")
mutate("web/v2/app.js", "function ", "window." + TR + " = 1;\nfunction ", TR)
mutate("web/v2/tab_set.js", '(legacyOn("classic") ? \'<a class="sx-it sx-lk" id="sx-display-classic" href="/classic"', '(true ? \'<a class="sx-it sx-lk" id="sx-display-classic" href="/classic"', "legacyOn")
with open(os.path.join(SR, "src", "brokers", "README.md"), "a", encoding="utf-8") as f:
    f.write("\n시험 자료 dev/20261004/x\n")
chk(any("증권사 README" in x for x in B.source_checks(SR)), "[5] 변이 잡음 — 개발 시험 경로")
shutil.copyfile(os.path.join(ROOT, "src", "brokers", "README.md"), os.path.join(SR, "src", "brokers", "README.md"))
with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
    CE = json.load(f)
for name, fn9, want in (
        ("지갑", lambda c: c.__setitem__("wallets", [{"address": "0x" + "ab" * 20}]), "wallets"),
        ("키 박힌 RPC", lambda c: c["bsc"].setdefault("logs_rpcs", []).append("https://bsc.invalid/v1/" + "f0" * 16), "bsc RPC"),
        ("바인딩", lambda c: c["web"].__setitem__("bind", "0.0.0.0"), "loopback"),
        ("공개 주소", lambda c: c["web"].__setitem__("public_url", "https://h.invalid"), "public_url"),
        ("메모 키", lambda c: c.__setitem__("_private_note", "x"), "'_' 메모 키"),
        ("AI 평가", lambda c: c["review"].__setitem__("sell_eval_daily_max", 5), "review"),
        ("원격 블록", lambda c: c.__setitem__("remote_access", {}), "remote_access")):
    c9 = json.loads(json.dumps(CE))
    fn9(c9)
    with open(os.path.join(SR, "config.example.json"), "w", encoding="utf-8") as f:
        json.dump(c9, f, ensure_ascii=False)
    got = B.source_checks(SR)
    chk(len(got) == 1 and want in got[0], f"[5] config.example 변이 잡음 — {name}", got)
shutil.rmtree(OUT, ignore_errors=True)

RJ = os.path.join(T.TMP, "rules_synth.json")
with open(RJ, "w", encoding="utf-8") as f:
    json.dump({"symbols": ["ZQXTOKEN"], "aliases": ["zqacct\\d+"], "subs": {"mid": [["zq-example\\.invalid", "포털"]]}}, f)
PICK = ("src/addr_ai.py", "web/v2/app.js", "public/README.md", "public/tests/test_pub_build.py")
sub = {s9: d9 for s9, d9 in p["files"].items() if s9 in PICK}
old_env = os.environ.pop("TJ_PUB_RULES", None)
try:
    B.strip_rules()
    chk(False, "[6] 규칙 없음 = ValueError")
except ValueError:
    chk(True, "[6] 규칙 없음 = ValueError")
with contextlib.redirect_stdout(io.StringIO()) as buf:
    rc6 = B.main(["build", os.path.join(T.TMP, "out_norules")])
chk(rc6 == 2 and not os.path.exists(os.path.join(T.TMP, "out_norules")), "[6] build 명령 규칙 없음 = rc 2 · 쓰기 0", buf.getvalue()[-200:])
os.environ["TJ_PUB_RULES"] = RJ
try:
    SM = B.strip_map(ROOT, sub, B.strip_rules())
finally:
    os.environ.pop("TJ_PUB_RULES", None)
    if old_env is not None:
        os.environ["TJ_PUB_RULES"] = old_env
chk(len(sub) == 4 and "src/addr_ai.py" in SM and "README.md" not in SM, "[6] 바뀐 파일 = 공개 대상만(README 원본 그대로)", sorted(SM))
chk(B.prove(ROOT, sub, SM) == [], "[6] strip 결과 증명 0(AST·바뀐 줄·noqa · JS 토큰)", B.prove(ROOT, sub, SM)[:5])
with open(os.path.join(ROOT, "src", "addr_ai.py"), encoding="utf-8", newline="") as f:
    A0 = f.read()
A1 = SM["src/addr_ai.py"].decode("utf-8")


def _stmt_lines(txt):
    return [(n.lineno, type(n).__name__) for n in ast.walk(ast.parse(txt)) if isinstance(n, ast.stmt)]


U2028 = [n for n in ast.walk(ast.parse(A0)) if isinstance(n, ast.Constant) and isinstance(n.value, str) and chr(0x2028) in n.value]
U2028b = [n for n in ast.walk(ast.parse(A1)) if isinstance(n, ast.Constant) and isinstance(n.value, str) and chr(0x2028) in n.value]
chk(len(U2028) >= 1 and [n.value for n in U2028] == [n.value for n in U2028b], "[6] U+2028 든 파이썬(addr_ai) = 그 글자 든 문자열 그대로(줄 나눔 = '\\n' 만)", len(U2028))
import tokenize  # noqa: E402
chk(B.strip_mode() == "all", "[6b] 기본 strip 모드 = all", B.strip_mode())
_cm = [t.string for t in tokenize.generate_tokens(io.StringIO(A1).readline) if t.type == tokenize.COMMENT]
_ds = [n for n in ast.walk(ast.parse(A1)) for b9 in [getattr(n, "body", None)] if isinstance(b9, list)
       for x in b9 if isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant) and isinstance(x.value.value, str)]
chk(all(c.startswith("# noqa") for c in _cm) and len(_ds) <= 1, "[6b] all = 남는 주석은 noqa 표식만 · 독스트링 = 모듈 영어 한 줄까지", (_cm[:3], len(_ds)))
os.environ["TJ_PUB_RULES"], os.environ["TJ_PUB_STRIP"] = RJ, "neutral"
try:
    SMn = B.strip_map(ROOT, sub, B.strip_rules())
    chk(B.prove(ROOT, sub, SMn) == [] and _stmt_lines(A0) == _stmt_lines(SMn["src/addr_ai.py"].decode("utf-8")),
        "[6b] neutral = 증명 0 · 문장 줄 자리 보존(U+2028 든 줄 포함)", B.prove(ROOT, sub, SMn)[:3])
    os.environ["TJ_PUB_STRIP"] = "zz"
    try:
        B.strip_mode()
        chk(False, "[6b] 모르는 모드 = ValueError")
    except ValueError:
        chk(True, "[6b] 모르는 모드 = ValueError")
finally:
    os.environ.pop("TJ_PUB_STRIP", None)
    os.environ.pop("TJ_PUB_RULES", None)
    if old_env is not None:
        os.environ["TJ_PUB_RULES"] = old_env
OUT6 = os.path.join(os.path.realpath(T.TMP), "pubout6")
B.copy_tree(ROOT, OUT6, sub, SM)
os.remove(os.path.join(OUT6, ".gitignore"))
with open(os.path.join(OUT6, ".gitignore"), "wb") as f:
    f.write(B.GITIGNORE.encode("utf-8"))
chk(B.verify(ROOT, OUT6, sub, SM) == [], "[6] 복사(strip 자리 = 결과 바이트) + 검사 0", B.verify(ROOT, OUT6, sub, SM))
shutil.copyfile(os.path.join(ROOT, "src", "addr_ai.py"), os.path.join(OUT6, sub["src/addr_ai.py"]))
chk(B.verify(ROOT, OUT6, sub, SM) == ["원본과 바이트 다름(strip 결과): " + sub["src/addr_ai.py"]], "[6] strip 자리에 원본 = 다름", B.verify(ROOT, OUT6, sub, SM))
BAD = dict(SM)
BAD["src/addr_ai.py"] = SM["src/addr_ai.py"] + b"\nzz_synth = 1\n"
chk(any("strip 증명 실패" in x and "AST" in x for x in B.prove(ROOT, sub, BAD)), "[6] 코드가 바뀐 결과 = 증명 실패", B.prove(ROOT, sub, BAD)[:3])
shutil.rmtree(OUT6, ignore_errors=True)
import json as _json  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools", "package"))
import pub_strip as PSt  # noqa: E402
_rel = next(iter(PSt.DATA_SCRUB))
_ln = _json.dumps({"k": "file.bytes", "m": "zqmod", "q": "<file>", "to": 123, "why": "합성 사유 zqacct1", "commit": "zq-branch"}, ensure_ascii=False)
_new = PSt.strip_data(_rel, _ln + "\n")
_r = _json.loads(_new.split("\n")[0])
chk(_r["to"] == 123 and _r["m"] == "zqmod" and "zqacct1" not in _new and "zq-branch" not in _new and PSt.data_check(_rel, _ln + "\n", _new) == [],
    "[6c] 기준선 사유·묶음 글만 고정 글 · 증명 0", _new[:200])
chk(PSt.data_check(_rel, _ln + "\n", _new.replace("123", "124")) != [], "[6c] 사유 밖 칸이 바뀌면 증명 실패")
_pub = frozenset({"tools/zq_pub.py", "tests/arch_baseline/zq.jsonl"})
_rel = "tests/arch_baseline/zq.jsonl"
_old = "\n".join([_json.dumps({"_doc": "정의 = docs/ARCH.md · 생성 tools/refactor/zq_gen.py · DESIGN_ACT1_ZQ 결정 1", "spec": "zq"}, ensure_ascii=False),
                  _json.dumps({"key": "tools/zq_pub.py", "n": 2, "why": "부르는 곳 tools/zq_priv.sh · tools/zq_pub.py"}, ensure_ascii=False),
                  _json.dumps({"key": "tools/zq_priv_20260101.sh", "n": 1}, ensure_ascii=False),
                  '{"m":"w","k":"tools/zq_priv.py::main","n":1}', '{"m":"w","k":"src/zq.py::f","n":1}']) + "\n"
_new = PSt.strip_base(_rel, _old, _pub)
_rows = [_json.loads(x) for x in _new.split("\n") if x]
chk(PSt.base_target(_rel) and not PSt.base_target("tests/arch_baseline/py_growth.jsonl") and not PSt.base_target("tests/x.json"),
    "[6d] 대상 = tests/arch_baseline/*.json(l) 중 DATA_SCRUB 밖")
chk([r.get("key") or r.get("k") for r in _rows] == [None, "tools/zq_pub.py", "src/zq.py::f"]
    and "zq_gen" not in _new and "DESIGN_" not in _new and "ARCH.md" not in _new and "zq_priv" not in _new
    and "tools/zq_pub.py" in _rows[1]["why"] and PSt.base_check(_rel, _old, _new, _pub) == [],
    "[6d] 비공개 열쇠 줄 2 뺌 · 설명 칸 비공개 이름 = 일반 이름(공개 경로는 그대로) · 증명 0", _new[:300])
chk(PSt.base_check(_rel, _old, _new.replace('"n": 2', '"n": 3'), _pub) != [], "[6d] 숫자가 바뀐 결과 = 증명 실패")
_bad = "\n".join(x for x in _new.split("\n") if "src/zq.py" not in x)
chk(PSt.base_check(_rel, _old, _bad, _pub) != [], "[6d] 공개 열쇠 줄을 뺀 결과 = 증명 실패")
_js = '{\n "_doc": "tools/refactor/zq_gen.py --emit 이 씀",\n "v": [1, 2]\n}\n'
_jn = PSt.strip_base("tests/arch_baseline/zq.json", _js, _pub)
chk(_jn == _js.replace("tools/refactor/zq_gen.py", PSt.PRIV_PATH_NAME) and PSt.base_check("tests/arch_baseline/zq.json", _js, _jn, _pub) == [],
    "[6d] .json = 설명 칸 글만 바꿈(나머지 바이트 그대로) · 증명 0", _jn)
SG = os.path.join(os.path.realpath(T.TMP), "gitroot7")
for rel7, body7 in (("tools/package/pub_files.txt", "docs/*.md\n"), ("docs/a.md", "# a\n"), (".gitignore", "docs/c.md\n")):
    os.makedirs(os.path.dirname(os.path.join(SG, rel7)), exist_ok=True)
    with open(os.path.join(SG, rel7), "w", encoding="utf-8") as f:
        f.write(body7)
G7 = ["git", "-C", SG, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false"]
subprocess.run(G7 + ["init", "-q"], check=True)
subprocess.run(G7 + ["add", "-A"], check=True)
subprocess.run(G7 + ["commit", "-q", "-m", "init"], check=True)
for rel7 in ("docs/b.md", "docs/c.md"):
    with open(os.path.join(SG, rel7), "w", encoding="utf-8") as f:
        f.write("# 작업 중\n")
e7 = B.plan(SG)["errors"]
chk(any("docs/b.md" in e and "추적 안 하는" in e for e in e7) and any("docs/c.md" in e and "추적 안 하는" in e for e in e7)
    and not any("docs/a.md" in e for e in e7), "[7] 미추적·무시 파일이 공개 목록에 걸림 = 막는 오류(추적 파일은 통과)", e7)
with open(os.path.join(SG, ".git", "index"), "wb") as f:
    f.write(b"DIRC broken")
chk(any("ls-files" in e for e in B.plan(SG)["errors"]) and B.tracked(SG) is False, "[7] git 뿌리인데 추적 목록 못 읽음 = 막는 오류", B.plan(SG)["errors"])
SN = os.path.join(os.path.realpath(T.TMP), "nogit7")
shutil.copytree(SG, SN, ignore=shutil.ignore_patterns(".git"))
chk(not any("추적 안 하는" in e for e in B.plan(SN)["errors"]) and B.tracked(SN) is None, "[7] git 뿌리 아님(사본) = 추적 검사 안 함", B.plan(SN)["errors"])
with open(os.path.join(SN, ".git"), "w") as f:
    f.write("gitdir: /nonexistent/tj_synthetic_gitdir\n")
chk(B.tracked(SN) is False and any("ls-files" in e for e in B.plan(SN)["errors"]), "[7] .git 있는데 뿌리 확인 실패 = 막는 오류(검사 생략 아님)", B.plan(SN)["errors"])
T.finish()
