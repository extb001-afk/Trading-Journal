#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "cfg_doc.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/cfg_doc.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음")
    T.finish()
sys.path.insert(0, TOOLS)
import cfg_doc as D  # noqa: E402
import cfg_schema as CS  # noqa: E402

b1, b2 = D.render(CS), D.render(CS)
chk(b1 == b2 and b1.endswith("\n"), "[1] 결정적 · 끝 줄바꿈")
lines = b1.split("\n")
chk(lines[0] == D.OPEN and lines[-2] == D.CLOSE and b1.count(D.OPEN) == 1 and b1.count(D.CLOSE) == 1, "[1] 표식 한 쌍(처음·끝)")
miss = [k[0] for k in CS.KEYS if "| `%s` |" % k[0] not in b1]
miss += ["%s.%s" % (b, s) for b, subs in CS.BLOCKS.items() for s, _d in subs if "| `%s.%s` |" % (b, s) not in b1]
miss += [k for k in CS.RUNTIME_KEYS if "`%s`" % k not in b1]
chk(not miss, "[1] 선언 키·닫힌 블록 하위 키·실행 주입 키가 다 들어감", miss)


def _cells(ln):
    return len(ln.replace("\\|", "").strip("|").split("|"))


tables, cur = [], []
for ln in lines + [""]:
    if ln.startswith("|"):
        cur.append(ln)
    elif cur:
        tables.append(cur)
        cur = []
chk(len(tables) == 2 and all(len({_cells(r) for r in t}) == 1 for t in tables), "[1] 표 2개 · 표마다 칸 수 같음(| 글자 가림)",
    [sorted({_cells(r) for r in t}) for t in tables])
chk(len(tables[0]) == len(CS.KEYS) + 2, "[1] 최상위 표 줄 = 선언 수 + 머리 2")

blk = b1
txt = "# 설정\n\n앞 글\n\n" + D.OPEN + "\n옛 블록\n" + D.CLOSE + "\n\n뒤 글\n"
new, how = D.splice(txt, blk)
chk(how == "replace" and new == "# 설정\n\n앞 글\n\n" + blk + "\n뒤 글\n", "[2] 표식 있음 = 블록 안만 바뀜(앞뒤 글 그대로)", repr(new[-40:]))
chk(D.splice(new, blk) == (new, "replace"), "[2] 다시 써도 같음")
new2, how2 = D.splice("# 설정\n\n손 표\n", blk)
chk(how2 == "append" and new2 == "# 설정\n\n손 표\n\n" + blk, "[2] 표식 없음 = 끝에 붙임(빈 줄 하나 사이)")
chk(D.splice(new2, blk) == (new2, "replace"), "[2] 붙인 뒤 다시 = 그대로")
for bad in ("a\n" + D.OPEN + "\n", "a\n" + D.CLOSE + "\n" + D.OPEN + "\n", D.OPEN + "\n" + D.OPEN + "\n" + D.CLOSE + "\n"):
    chk(D.splice(bad, blk)[0] is None, "[2] 표식 짝 안 맞음 = 거부", repr(bad))

tool = os.path.join(TOOLS, "cfg_doc.py")
doc = os.path.join(T.TMP, "CONFIG.md")


def run(*a):
    p = subprocess.run([sys.executable, "-I", tool, "--root", T.ROOT] + list(a), capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


rc, out = run()
chk(rc == 0 and out == b1, "[3] 인자 없음 = 블록 글 출력")
chk(run("--check", os.path.join(T.TMP, "없는.md"))[0] == 0, "[3] --check 파일 없음 = rc 0(건너뜀)")
chk(run("--write", os.path.join(T.TMP, "없는.md"))[0] == 2, "[3] --write 파일 없음 = rc 2")
with open(doc, "w", encoding="utf-8") as f:
    f.write("# 설정\n\n손 표\n")
chk(run("--check", doc)[0] == 1, "[3] --check 표식 없음 = rc 1")
chk(run("--write", doc)[0] == 0 and open(doc, encoding="utf-8").read() == new2, "[3] --write 표식 없음 = 끝에 붙임")
chk(run("--check", doc)[0] == 0, "[3] --check 같음 = rc 0")
with open(doc, "a", encoding="utf-8") as f:
    f.write("꼬리\n")
s = open(doc, encoding="utf-8").read().replace("| `wallets` |", "| `wallet` |")
with open(doc, "w", encoding="utf-8") as f:
    f.write(s)
chk(run("--check", doc)[0] == 1, "[3] --check 블록 다름 = rc 1")
chk(run("--write", doc)[0] == 0 and open(doc, encoding="utf-8").read() == new2 + "꼬리\n", "[3] --write = 블록만 고침 · 블록 밖 글 그대로")

with open(doc, "w", encoding="utf-8") as f:
    f.write(new2 + D.OPEN + "\n")
chk(run("--check", doc)[0] == 1 and run("--write", doc)[0] == 2, "[3] 표식이 한 쌍이 아니면 --check rc 1 · --write 거부")
with open(doc, "wb") as f:
    f.write("# 설정\r\n\r\n손 표\r\n".encode("utf-8"))
rc, _o = run("--write", doc)
raw = open(doc, "rb").read()
chk(rc == 0 and raw.startswith("# 설정\r\n\r\n손 표\r\n".encode("utf-8")) and raw.endswith(blk.encode("utf-8")), "[3] CRLF 문서 = 블록 밖 바이트 그대로")

real = os.path.join(T.ROOT, D.DOC)
if os.path.isfile(real):
    rc, out = run("--check", real)
    chk(rc == 0, "[4] public/docs/CONFIG.md 블록 = 선언표(다르면 `python3 -I tools/refactor/cfg_doc.py --write`)", out)
else:
    chk(True, "[4] public/docs/CONFIG.md 없음(10-6 전) — 건너뜀")
T.finish()
