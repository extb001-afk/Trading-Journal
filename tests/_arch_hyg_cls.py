from __future__ import annotations

import ast
import json
import os
import re

_HREAD = frozenset(["web_src", "core_src", "mod_src"])
_OPEN = frozenset(["open"])
_OPEN_MODS = frozenset(["io", "codecs", "tokenize", "os", "builtins", "gzip", "bz2", "lzma"])
_READ_ATTR = frozenset(["read_text", "read_bytes"])
_GETSRC = frozenset(["getsource", "getsourcelines"])
ARCH_PREFIX = "test_arch_"
_PATH_FUNCS = frozenset(["join", "abspath", "realpath", "normpath", "dirname", "relpath", "expanduser", "fspath", "Path", "PurePath",
                         "joinpath", "resolve", "with_name", "with_suffix", "glob", "iglob", "rglob", "iterdir", "listdir", "scandir",
                         "walk", "sorted", "list", "tuple", "set", "str", "reversed", "iter", "filter"])
_CODE_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+([A-Za-z_][\w.]*)[ \t]+import[ \t]+([\w, \t]+)|import[ \t]+([A-Za-z_][\w., \t]*))", re.M)


def _attr(n: ast.AST) -> str | None:
    return n.attr if isinstance(n, ast.Attribute) else n.id if isinstance(n, ast.Name) else None


def arch_named(filename: str) -> bool:
    return os.path.basename(filename).startswith(ARCH_PREFIX)


class _Reads:
    def __init__(self, tree: ast.Module):
        self.nodes = list(ast.walk(tree))
        self.h = {a.asname or a.name for n in self.nodes if isinstance(n, ast.Import) for a in n.names if a.name == "_harness"}
        self.from_h = {a.asname or a.name: a.name for n in self.nodes
                       if isinstance(n, ast.ImportFrom) and n.module == "_harness" for a in n.names}
        self.sets: dict[str, set[str]] = {"roots": set(), "paths": set()}
        self._names(lambda v: self._is_h(v, "ROOT") or (isinstance(v, ast.Call) and _attr(v.func) in ("abspath", "realpath", "Path")
                                                       and v.args and self._is_root(v.args[0])), "roots")
        self._names(self.mentions, "paths")

    def _is_h(self, n: ast.AST, name: str) -> bool:
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in self.h:
            return n.attr == name
        return isinstance(n, ast.Name) and self.from_h.get(n.id) == name

    def _is_root(self, n: ast.AST) -> bool:
        if self._is_h(n, "ROOT") or (isinstance(n, ast.Name) and n.id in self.sets["roots"]):
            return True
        return isinstance(n, ast.Call) and _attr(n.func) in ("Path", "PurePath") and len(n.args) == 1 and self._is_root(n.args[0])

    @staticmethod
    def _src_word(n: ast.AST) -> bool:
        return isinstance(n, ast.Constant) and isinstance(n.value, str) and (n.value.strip("/") == "src" or n.value.startswith("src/"))

    def _fixed(self, n: ast.AST) -> bool:
        if self._is_h(n, "SRC"):
            return True
        if isinstance(n, ast.Call) and _attr(n.func) in ("join", "Path", "PurePath", "joinpath") and len(n.args) >= 2:
            return self._is_root(n.args[0]) and self._src_word(n.args[1])
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            return self._is_root(n.left) and self._src_word(n.right)
        return False

    def mentions(self, e: ast.AST | None, hidden: frozenset = frozenset()) -> bool:
        if e is None:
            return False
        if self._fixed(e):
            return True
        if isinstance(e, ast.Name):
            return e.id in self.sets["paths"] and e.id not in hidden
        if isinstance(e, ast.Call):
            return _attr(e.func) in _PATH_FUNCS and (any(self.mentions(a, hidden) for a in e.args) or
                                                     (isinstance(e.func, ast.Attribute) and self.mentions(e.func.value, hidden)))
        if isinstance(e, (ast.Subscript, ast.Starred, ast.FormattedValue, ast.Attribute)):
            return self.mentions(e.value, hidden)
        if isinstance(e, ast.BinOp):
            return self.mentions(e.left, hidden) or self.mentions(e.right, hidden)
        if isinstance(e, ast.IfExp):
            return self.mentions(e.body, hidden) or self.mentions(e.orelse, hidden)
        if isinstance(e, (ast.List, ast.Tuple, ast.Set)):
            return any(self.mentions(x, hidden) for x in e.elts)
        if isinstance(e, ast.JoinedStr):
            return any(self.mentions(x, hidden) for x in e.values)
        if isinstance(e, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            return self.mentions(e.elt, hidden) or any(self.mentions(g.iter, hidden) for g in e.generators)
        return False

    def _names(self, pred, key: str) -> None:
        pairs = []
        for n in self.nodes:
            if isinstance(n, ast.Assign):
                pairs += [(t, n.value) for t in n.targets]
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and n.value is not None:
                pairs.append((n.target, n.value))
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                pairs.append((n.target, n.iter))
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                pairs.append((n.optional_vars, n.context_expr))
        out = self.sets[key]
        while True:
            more = {x.id for t, v in pairs if pred(v) for x in ast.walk(t) if isinstance(x, ast.Name)} - out
            if not more:
                return
            out |= more

    def _opens_param(self) -> set[str]:
        out = set()
        for f in self.nodes:
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                params = {a.arg for a in f.args.args + f.args.posonlyargs + f.args.kwonlyargs}
                for c in ast.walk(f):
                    if isinstance(c, ast.Call) and self._opener(c) is not None and any(
                            isinstance(x, ast.Name) and x.id in params for x in ast.walk(self._opener(c))):
                        name = f.name if not isinstance(f, ast.Lambda) else None
                        if name:
                            out.add(name)
                        break
        out |= {t.id for n in self.nodes if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda)
                for t in n.targets if isinstance(t, ast.Name) and self._lambda_opens(n.value)}
        return out

    def _lambda_opens(self, lam: ast.Lambda) -> bool:
        params = {a.arg for a in lam.args.args}
        return any(isinstance(c, ast.Call) and self._opener(c) is not None and
                   any(isinstance(x, ast.Name) and x.id in params for x in ast.walk(self._opener(c))) for c in ast.walk(lam))

    @staticmethod
    def _opener(c: ast.Call) -> ast.AST | None:
        nm = _attr(c.func)
        if nm in _OPEN:
            if isinstance(c.func, ast.Attribute) and _attr(c.func.value) not in _OPEN_MODS:
                return c.func.value
            if c.args:
                return c.args[0]
            return next((k.value for k in c.keywords if k.arg in ("file", "filename")), None)
        if nm in _READ_ATTR and isinstance(c.func, ast.Attribute):
            return c.func.value
        return None

    def sites(self, tree: ast.Module) -> list[int]:
        helpers = self._opens_param()
        out = set()
        stack = [(tree, frozenset())]
        while stack:
            node, hidden = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = node.args
                hidden = hidden | {x.arg for x in a.args + a.posonlyargs + a.kwonlyargs}
            if isinstance(node, ast.Call):
                c, nm = node, _attr(node.func)
                p = self._opener(c)
                if (p is not None and self.mentions(p, hidden)) or (nm in _HREAD and self._h_call(c.func)) or nm in _GETSRC or (
                        isinstance(c.func, ast.Name) and c.func.id in helpers
                        and any(self.mentions(x, hidden) for x in c.args + [k.value for k in c.keywords])):
                    out.add(c.lineno)
            stack += [(ch, hidden) for ch in ast.iter_child_nodes(node)]
        return sorted(out)

    def _h_call(self, f: ast.AST) -> bool:
        if isinstance(f, ast.Attribute):
            return isinstance(f.value, ast.Name) and f.value.id in self.h
        return isinstance(f, ast.Name) and self.from_h.get(f.id) in _HREAD


def src_reads(text: str, filename: str = "<글>") -> list[int]:
    tree = ast.parse(text, filename)
    return _Reads(tree).sites(tree)


def _test_files(tests_dir: str) -> list[str]:
    return sorted(f for f in os.listdir(tests_dir) if f.startswith("test_") and f.endswith(".py"))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def src_readers(tests_dir: str) -> dict[str, list[int]]:
    out = {}
    for fn in _test_files(tests_dir):
        if not arch_named(fn):
            lines = src_reads(_read(os.path.join(tests_dir, fn)), fn)
            if lines:
                out[fn] = lines
    return out


def src_modules(src_dir: str) -> set[str]:
    out = set()
    for dp, dns, fns in os.walk(src_dir):
        dns[:] = sorted(d for d in dns if not d.startswith((".", "_")))
        rel = os.path.relpath(dp, src_dir)
        pre = "" if rel == "." else rel.replace(os.sep, ".") + "."
        for fn in fns:
            if fn.endswith(".py"):
                stem = fn[:-3]
                out.add(pre[:-1] if stem == "__init__" and pre else pre + stem)
    return out


def imported_modules(text: str, filename: str, mods: set[str]) -> set[str]:
    tree = ast.parse(text, filename)
    got: set[str] = set()
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}

    def add(name: str, subs=()):
        if not name:
            return
        parts = name.split(".")
        got.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
        got.update(name + "." + s for s in subs)

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                add(a.name)
        elif isinstance(n, ast.ImportFrom) and not n.level:
            add(n.module or "", [a.name for a in n.names])
        elif isinstance(n, ast.Call) and _attr(n.func) in ("import_module", "__import__") and n.args \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            add(n.args[0].value)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and "import" in n.value and id(n) not in docs:
            for m in _CODE_IMPORT.finditer(n.value):
                if m.group(1):
                    add(m.group(1), [s.strip().split()[0] for s in m.group(2).split(",") if s.strip()])
                else:
                    for s in m.group(3).split(","):
                        add(s.strip().split()[0] if s.strip() else "")
    return got & mods


def untested(tests_dir: str, src_dir: str) -> list[str]:
    mods = src_modules(src_dir)
    seen: set[str] = set()
    for fn in _test_files(tests_dir):
        seen |= imported_modules(_read(os.path.join(tests_dir, fn)), fn, mods)
    return sorted(mods - seen)


def kinds(tests_dir: str) -> dict[str, str]:
    listed: set[str] = set()
    p = os.path.join(tests_dir, "arch_baseline", "hyg_srctext.jsonl")
    if os.path.isfile(p):
        for ln in _read(p).splitlines():
            rec = json.loads(ln) if ln.strip() else {}
            if rec.get("set") == "src_readers":
                listed.add(rec.get("key"))
    return {fn: "arch" if arch_named(fn) or fn in listed else "behavior" for fn in _test_files(tests_dir)}
