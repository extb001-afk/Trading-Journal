#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import re
import sys
import unicodedata

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _arch_ratchet as R  # noqa: E402

SPEC = R.Spec("ref_common", "max", ("attr", "imp", "sh"), "ref.common — 파일별 common 참조(속성 · import · 셸 heredoc)",
              "파일별 common 참조 수 — attr = common.X 속성 참조(별칭 포함) · imp = common 대상 Import·ImportFrom·import_module 자리 · "
              "sh = tools 셸 대본의 heredoc import 줄. 늘면 실패 · 줄면 안내 · 4-6 끝 목표 0(정의 = _arch_refcommon 머리).",
              {"*": "common 을 새로 부르지 말고 정의 모듈(paths · statefile · logs 등)을 바로 import 하라 — 옮김 전 이름이면 총괄에 보고"})
R.SPECS.setdefault(SPEC.name, SPEC)
CMD = "python3 public/tests/_arch_refcommon.py"
_SH = re.compile(r"\bimport\s+(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*common\b|\bfrom\s+common\s+import\b")
_SKIP = {"__pycache__", "dev", ".git", "node_modules"}


def _bound(tree: ast.AST) -> tuple:
    mine, other = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mine |= {a.asname or "common" for a in n.names if a.name == "common"}
            other |= {a.asname or a.name.split(".")[0] for a in n.names if a.name != "common"}
    return mine, other


def count_py(text: str) -> dict:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"attr": 0, "imp": 0, "err": 1}
    names, mods = _bound(tree)
    loaders = {"import_module", "__import__"} | {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                                                 and n.module in ("importlib", "builtins") for a in n.names
                                                 if a.name in ("import_module", "__import__")}
    attr = imp = 0
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and (
                n.value.id in names or (n.attr == "common" and n.value.id in mods)):
            attr += 1
        elif isinstance(n, ast.Import):
            imp += sum(1 for a in n.names if a.name == "common" or a.name.startswith("common."))
        elif isinstance(n, ast.ImportFrom):
            imp += int(n.level == 0 and (n.module == "common" or (n.module or "").startswith("common.")
                                         or any(a.name == "common" for a in n.names)))
        elif isinstance(n, ast.Call) and _names_common(n):
            f = n.func
            fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            imp += int(fname in loaders)
    return {"attr": attr, "imp": imp}


def _names_common(call) -> bool:
    vals = call.args[:1] + [k.value for k in call.keywords if k.arg == "name"]
    return any(isinstance(v, ast.Constant) and v.value == "common" for v in vals)


def _may_refer(text: str) -> bool:
    t = text if text.isascii() else unicodedata.normalize("NFKC", text)
    return "common" in t or "import_module" in t or "__import__" in t


def count_sh(text: str) -> dict:
    t = text if text.isascii() else unicodedata.normalize("NFKC", text)
    return {"sh": sum(1 for ln in t.replace("\\\n", " ").split("\n") if _SH.search(ln))}


def _files(root: str):
    for top, exts in (("src", (".py",)), ("tools", (".py", ".sh")), (os.path.join("public", "tests"), (".py",))):
        base = os.path.join(root, top)
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(d for d in dns if d not in _SKIP)
            for fn in sorted(fns):
                if fn.endswith(exts):
                    yield os.path.join(dp, fn)


def scan(root: str) -> dict:
    out = {}
    for p in _files(root):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if not _may_refer(text):
            continue
        v = count_sh(text) if p.endswith(".sh") else count_py(text)
        if any(v.values()):
            out[rel] = v
    return out


def current(root: str) -> dict:
    return R._doc({k: {f: v.get(f, 0) for f in SPEC.fields} for k, v in scan(root).items()})


def totals(doc: dict) -> dict:
    return {f: sum(v.get(f, 0) for v in doc["items"].values()) for f in SPEC.fields}


def main(argv: list) -> int:
    mode = next((a for a in argv if a.startswith("--")), "--show")
    if mode not in ("--show", "--update-lower", "--freeze"):
        print(__doc__)
        return 2
    if not R.repo_layout():
        print("저장소 배치가 아님(공개판 배치) — 기준선이 없어 할 일 없음")
        return 1
    root = R._root()
    sc = scan(root)
    errs = sorted(k for k, v in sc.items() if v.get("err"))
    if errs:
        print("파싱 실패(셈 못 함): " + ", ".join(errs[:10]))
    cur = current(root)
    base = R.load(SPEC.name)
    if mode == "--show":
        bad, stale = R.compare(SPEC, cur, base or R._doc())
        print(f"[{SPEC.name}] 실패 {len(bad)} · 좋아짐 {len(stale)}" + ("" if base else " (기준선 없음)") +
              " · 합계 " + " · ".join("%s %d" % kv for kv in totals(cur).items()) + f" · 파일 {len(cur['items'])}")
        for x in bad + stale:
            print("   " + x)
        return 0
    if base is None and mode == "--update-lower":
        print(f"[{SPEC.name}] 기준선 없음 — --freeze(총괄)로 처음 만든다")
        return 1
    new = R.tighten(SPEC, cur, base) if mode == "--update-lower" else R.freeze(SPEC, cur, base)
    text = R.dump(SPEC, new)
    path = os.path.join(R.BASE_DIR, SPEC.name + ".jsonl")
    old = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
    if text != old:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"[{SPEC.name}] 기준선 씀 — {len(new['items'])}파일 · 합계 " + " · ".join("%s %d" % kv for kv in totals(new).items()))
    else:
        print(f"[{SPEC.name}] 그대로")
    left = R.compare(SPEC, cur, new)[0]
    if left:
        print(f"[{SPEC.name}] 여전히 실패 {len(left)}건 — 기준선은 안 올림: {left[0][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
