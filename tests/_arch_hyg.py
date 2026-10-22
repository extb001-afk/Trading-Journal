from __future__ import annotations

import ast
import os
import re

from _arch_hyg_patch import SrcIndex, _name_of, monkeypatches
from _arch_hyg_src import _MAY_READ, _SCOPE, scopes, source_checks


_MMDD = r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
_ROUND = re.compile("|".join([
    r"(?<=[A-Za-z_])" + _MMDD + r"(?!\d)",
    r"(?<![0-9A-Za-z])" + _MMDD + r"[a-z](?![A-Za-z0-9])",
    r"(?<!\d)20\d\d" + _MMDD + r"(?!\d)",
    r"(?<![\d.\-])(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?![\d\-])",
    r"(?<![A-Za-z0-9_])[a-z]{2,3}\d{2,3}[a-z]?(?![A-Za-z0-9_])",
    r"(?<![A-Za-z0-9_])s\d{2}[a-z]?(?![A-Za-z0-9_])",
    r"(?<!\d)[1-9]\d차(?![가-힣])",
    r"코덱스|codex|외부 (?:리뷰|재검토|검증|검토|심층)",
]))
_NOT_ROUND = frozenset(["sha224", "sha256", "sha384", "sha512", "aes128", "aes256", "int128", "int256", "int32", "int64",
                        "md160", "erc20", "bep20", "trc20", "brc20", "erc721", "bep721", "utf16", "utf32", "x509"])
_NAME_ID = re.compile(r"^(?:[a-z]{1,3}(?:\d{2,3}[a-z]?|\d[a-z])|(?:20\d\d)?" + _MMDD + r"[a-z]{0,2})$")


def round_markers(text: str) -> list[str]:
    return [m for m in _ROUND.findall(text) if m not in _NOT_ROUND]


def round_named(filename: str) -> bool:
    stem = re.sub(r"^test_|\.py$", "", filename)
    return any(round_markers(w) or (_NAME_ID.match(w) and w not in _NOT_ROUND) for w in stem.split("_"))


def _static_text(e: ast.AST | None) -> str | None:
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        return e.value
    if isinstance(e, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in e.values)
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Mod):
        return _static_text(e.left)
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        parts = [_static_text(e.left), _static_text(e.right)]
        return None if parts == [None, None] else "".join(p or "{}" for p in parts)
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "format":
        return _static_text(e.func.value)
    return None


def _label_arg(c: ast.Call, pos: int, kw: str | None) -> ast.AST | None:
    if len(c.args) > pos and not any(isinstance(a, ast.Starred) for a in c.args[:pos + 1]):
        return c.args[pos]
    return next((k.value for k in c.keywords if k.arg == kw), None) if kw else None


def _call_key(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id + "." + func.attr
    return None


def label_of(c: ast.Call, pos: dict, shadow: dict | None = None) -> tuple | None:
    if _name_of(c.func) == "chk":
        return 1, "msg"
    key = _call_key(c.func)
    if key and shadow and key.split(".")[0] in shadow.get(id(c), ()):
        return None
    return pos.get(key)


def _bound(fn: ast.AST) -> set[str]:
    a = fn.args
    out = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | {x.arg for x in (a.vararg, a.kwarg) if x}
    stack: list[ast.AST] = list(fn.body) if isinstance(fn.body, list) else []
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            continue
        if isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {(x.asname or x.name).split(".")[0] for x in n.names}
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        stack += list(ast.iter_child_nodes(n))
    return out


def shadows(sc: dict[ast.AST, list[ast.AST]]) -> dict[int, set[str]]:
    parent: dict[int, ast.AST] = {}
    for owner, ns in sc.items():
        for n in ns:
            if isinstance(n, _SCOPE):
                parent[id(n)] = owner
    out: dict[int, set[str]] = {}
    bound_memo: dict[int, set[str]] = {}
    for owner, ns in sc.items():
        if not isinstance(owner, _SCOPE):
            continue
        names: set[str] = set()
        f = owner
        while isinstance(f, _SCOPE):
            if id(f) not in bound_memo:
                bound_memo[id(f)] = _bound(f) if not isinstance(f, ast.Lambda) else {x.arg for x in f.args.args}
            names |= bound_memo[id(f)]
            f = parent.get(id(f))
        for n in ns:
            if isinstance(n, ast.Call):
                out[id(n)] = names
    return out


def label_funcs(nodes: list[ast.AST], sc: dict[ast.AST, list[ast.AST]], imported: dict | None = None,
                shadow: dict | None = None) -> dict[str, tuple[int, str | None]]:
    tree = nodes[0] if nodes and isinstance(nodes[0], ast.Module) else None
    top = tree.body if tree else []
    defs = [n for n in top if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    rebound = {t.id for st in top if isinstance(st, ast.Assign) for t in st.targets if isinstance(t, ast.Name)}
    local = {n.name for n in defs} | rebound
    pos: dict[str, tuple[int, str | None]] = {k: v for k, v in (imported or {}).items()
                                              if (k.split(".")[0] not in rebound if "." in k else k not in local)}
    fns = [(n, [c for c in sc.get(n, ()) if isinstance(c, ast.Call)]) for n in defs]
    changed = True
    while changed:
        changed = False
        for f, calls in fns:
            if f.name in pos:
                continue
            params = [a.arg for a in f.args.args]
            for c in (n for n in calls if label_of(n, pos, shadow)):
                arg = _label_arg(c, *label_of(c, pos, shadow))
                used = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)} & set(params) if arg is not None else set()
                if used:
                    p = min(params.index(u) for u in used)
                    pos[f.name] = (p, params[p])
                    changed = True
                    break
    return pos


def helper_labels(tests_dir: str) -> dict[str, dict]:
    out = {}
    for fn in sorted(os.listdir(tests_dir)):
        if fn.startswith("_") and fn.endswith(".py") and fn != "_harness.py" and not fn.startswith("_arch"):
            with open(os.path.join(tests_dir, fn), encoding="utf-8") as f:
                tree = ast.parse(f.read(), fn)
            sco = scopes(tree)
            pos = label_funcs([tree] + [n for ns in sco.values() for n in ns], sco, None, shadows(sco))
            if pos:
                out[fn[:-3]] = pos
    return out


def _imported_labels(nodes: list[ast.AST], helpers: dict) -> dict:
    out = {}
    for n in nodes:
        if isinstance(n, ast.ImportFrom) and not n.level and n.module in helpers:
            out.update({a.asname or a.name: helpers[n.module][a.name] for a in n.names if a.name in helpers[n.module]})
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.update({(a.asname or a.name) + "." + f: v for f, v in helpers.get(a.name, {}).items()})
    return out


def check_labels(tree: ast.Module, nodes: list[ast.AST] | None = None, pos: dict | None = None,
                 shadow: dict | None = None) -> list[tuple[int, str]]:
    nodes = nodes if nodes is not None else list(ast.walk(tree))
    pos = pos if pos is not None else label_funcs(nodes, scopes(tree))
    out = []
    for c in (n for n in nodes if isinstance(n, ast.Call) and label_of(n, pos, shadow)):
        txt = _static_text(_label_arg(c, *label_of(c, pos, shadow)))
        if txt is not None:
            out.append((c.lineno, txt))
    return sorted(out)


def check_sites(tree: ast.Module, nodes: list[ast.AST] | None = None, pos: dict | None = None, shadow: dict | None = None) -> int:
    nodes = nodes if nodes is not None else list(ast.walk(tree))
    pos = pos if pos is not None else label_funcs(nodes, scopes(tree))
    return sum(1 for n in nodes if (isinstance(n, ast.Call) and label_of(n, pos, shadow)) or isinstance(n, ast.Assert))


def analyze_test(text: str, filename: str = "<글>", idx: SrcIndex | None = None, helpers: dict | None = None) -> dict:
    tree = ast.parse(text, filename)
    sco = scopes(tree)
    nodes = [tree] + [n for ns in sco.values() for n in ns]
    hself = os.path.basename(filename) == "_harness.py"
    sc, neg = source_checks(tree, nodes, hself, sco) if hself or _MAY_READ.search(text) else ([], [])
    mp = monkeypatches(tree, nodes, idx)
    shadow = shadows(sco)
    pos = label_funcs(nodes, sco, _imported_labels(nodes, helpers or {}), shadow)
    labels = check_labels(tree, nodes, pos, shadow)
    rl = [ln for ln, t in labels if round_markers(t)]
    return {"str_checks": len(sc), "str_neg": len(neg), "patch_attr": len(mp["attr"]), "patch_call": len(mp["call"]),
            "patch_foreign": len(mp["foreign"]), "round_labels": len(rl), "checks": check_sites(tree, nodes, pos, shadow),
            "labels": len(labels),
            "lines": {"str_checks": sc, "str_neg": neg, "patch_attr": mp["attr"], "patch_call": mp["call"],
                      "patch_foreign": [x[0] for x in mp["foreign"]], "round_labels": rl},
            "foreign": mp["foreign"], "reads_readme": _reads_readme(nodes)}


def _reads_readme(nodes: list[ast.AST]) -> bool:
    return any((isinstance(n, ast.Attribute) and n.attr == "README") or
               (isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(r"README(\.md)?$", n.value)) or
               (isinstance(n, ast.Call) and _name_of(n.func) == "doc_text" and not n.args)
               for n in nodes)


def test_hygiene(tests_dir: str, src_dir: str | None = None) -> dict:
    idx = SrcIndex(src_dir) if src_dir else None
    helpers = helper_labels(tests_dir)
    out = {}
    for fn in sorted(f for f in os.listdir(tests_dir) if f.endswith(".py")):
        with open(os.path.join(tests_dir, fn), encoding="utf-8") as f:
            out[fn] = analyze_test(f.read(), fn, idx, helpers)
    return out
