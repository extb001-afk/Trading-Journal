#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _arch_ratchet as R  # noqa: E402
from _arch_split import fold_count  # noqa: E402

SPEC = R.Spec("py_unit_closure", "max", ("n",), "유닛 import 폐포 크기(pm2 유닛 입구별 모듈 수)",
              "pm2 유닛마다 입구(+ 러너 unit_runner)에서 닿는 import 폐포의 노드 수(src 모듈 · 하위 패키지 · tools 대본) — 늘면 실패 · 줄면 안내. "
              "그래프 = tools/deploy_lib.sh 유닛 표·동적 간선 + AST import(지연 포함) · 정의 = _arch_closure 머리.",
              {"*": "유닛이 새 모듈을 싣게 됐다 — 꼭 필요한 import 인지 보고(지연 import 도 셈), 필요하면 총괄이 --freeze(사유 커밋)"})
R.SPECS.setdefault(SPEC.name, SPEC)
CMD = "python3 public/tests/_arch_closure.py"


def _block(text: str, var: str) -> str | None:
    m = re.search(r"^%s='\n(.*?)^'\n" % var, text, re.S | re.M)
    return m.group(1) if m else None


def _rows(text: str, ncol: int) -> list:
    out = []
    for ln in (text or "").splitlines():
        body = ln.split("#", 1)[0].strip()
        if body:
            f = body.split()
            if len(f) != ncol:
                raise ValueError("칸 %d개여야: %r" % (ncol, body))
            out.append(f)
    return out


def unit_table(root: str):
    p = os.path.join(root, "tools", "deploy_lib.sh")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        t = f.read()
    tbl, edg = _block(t, "DEPLOY_UNIT_TABLE"), _block(t, "DEPLOY_DYN_EDGES")
    if tbl is None or edg is None:
        raise ValueError("tools/deploy_lib.sh 에서 DEPLOY_UNIT_TABLE·DEPLOY_DYN_EDGES 블록을 못 찾음")
    return _rows(tbl, 7), _rows(edg, 3)


def _imports(path: str) -> set:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module.split(".")[0])
    return out


def graph(root: str, table: list, edges: list) -> tuple:
    src = os.path.join(root, "src")
    mods = {f[:-3] for f in os.listdir(src) if f.endswith(".py") and os.path.isfile(os.path.join(src, f))}
    pkgs = {d for d in os.listdir(src) if d != "__pycache__" and os.path.isdir(os.path.join(src, d))
            and not os.path.islink(os.path.join(src, d))
            and any(fn.endswith(".py") for _r, _d, fs in os.walk(os.path.join(src, d)) for fn in fs)}
    nodes = mods | pkgs
    g = {m: _imports(os.path.join(src, m + ".py")) & nodes for m in mods}
    for p in pkgs:
        acc = set()
        for r9, ds, fs in os.walk(os.path.join(src, p)):
            ds[:] = [x for x in ds if x != "__pycache__"]
            for fn in fs:
                if fn.endswith(".py"):
                    acc |= _imports(os.path.join(r9, fn))
        g[p] = (acc & nodes) - {p}

    def node(path):
        if path.startswith("src/") and path.endswith(".py"):
            rel = path[4:]
            if "/" not in rel:
                return rel[:-3] if rel[:-3] in mods else None
            top = rel.split("/", 1)[0]
            return top if top in pkgs else None
        if path.startswith("tools/") and path.endswith(".py") and "/" not in path[6:]:
            return path if os.path.isfile(os.path.join(root, path)) else None
        return None

    def script(nd):
        if nd.startswith("tools/") and nd not in g:
            g[nd] = _imports(os.path.join(root, nd)) & nodes

    chain = [r[1] for r in table if r[3] == "chain"]
    for frm, how, tgt in edges:
        if frm not in g:
            continue
        for t9 in (chain if tgt == "@chain" else [tgt]):
            nd = node(t9)
            if nd is None:
                continue
            g[frm] = g[frm] | {nd}
            if how != "run":
                script(nd)
    for r in table:
        nd = node(r[1]) if r[1] != "-" else None
        if nd:
            script(nd)
    return g, node


def closures(root: str) -> dict | None:
    ut = unit_table(root)
    if ut is None:
        return None
    table, edges = ut
    g, node = graph(root, table, edges)
    out = {}
    for name, entry, runner, *_rest in table:
        nd = node(entry) if entry != "-" else None
        if nd is None:
            continue
        starts = {nd} | ({"unit_runner"} if runner != "-" and "unit_runner" in g else set())
        seen, st = set(), list(starts)
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            st.extend(g.get(x, ()))
        out[name] = sorted(seen)
    return out


def split_table() -> dict:
    p = os.path.join(R.BASE_DIR, "layers.json")
    try:
        with open(p, encoding="utf-8") as f:
            got = json.load(f).get("split_of")
    except (OSError, ValueError, AttributeError):
        return {}
    return got if isinstance(got, dict) else {}


def counted(cl: dict, split_of: dict | None = None) -> dict:
    so = split_table() if split_of is None else split_of
    return R._doc({u: {"n": fold_count(v, so)} for u, v in cl.items()})


def current(root: str) -> dict | None:
    cl = closures(root)
    return None if cl is None else counted(cl)


def main(argv: list) -> int:
    mode = next((a for a in argv if a.startswith("--")), "--show")
    want = [a for a in argv if not a.startswith("--")]
    if mode not in ("--show", "--update-lower", "--freeze"):
        print(__doc__)
        return 2
    if not R.repo_layout():
        print("저장소 배치가 아님(공개판 배치) — 기준선·배포 도구가 없어 할 일 없음")
        return 1
    root = R._root()
    cl = closures(root)
    if cl is None:
        print("tools/deploy_lib.sh 없음 — 할 일 없음")
        return 1
    cur = counted(cl)
    base = R.load(SPEC.name)
    if mode == "--show":
        bad, stale = R.compare(SPEC, cur, base or R._doc())
        print(f"[{SPEC.name}] 실패 {len(bad)} · 좋아짐 {len(stale)}" + ("" if base else " (기준선 없음)"))
        for x in bad + stale:
            print("   " + x)
        for u in sorted(cl):
            b9 = (base or R._doc())["items"].get(u, {}).get("n")
            n9 = cur["items"][u]["n"]
            print("   %-10s %4d개%s%s" % (u, n9, "" if n9 == len(cl[u]) else f" (실제 {len(cl[u])} · 분할 접음)",
                                        "" if b9 is None else f" (기준선 {b9})"))
        for u in want:
            print(f"\n[{u}] 폐포 {len(cl.get(u, []))}개: " + " ".join(cl.get(u, ["(그런 유닛 없음)"])))
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
        print(f"[{SPEC.name}] 기준선 씀 — {len(new['items'])}유닛")
    else:
        print(f"[{SPEC.name}] 그대로")
    left = R.compare(SPEC, cur, new)[0]
    if left:
        print(f"[{SPEC.name}] 여전히 실패 {len(left)}건 — 기준선은 안 올림: {left[0][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
