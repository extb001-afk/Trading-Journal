from __future__ import annotations

import ast
import os


def _name_of(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _root_of(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


_PATCH_FUNCS = frozenset(["setattr", "delattr", "patch_moved", "patch_cls_attr"])


class SrcIndex:

    def __init__(self, src_dir: str):
        self.src = src_dir
        self._memo: dict[str, dict | None] = {}

    def _file(self, mod: str) -> str | None:
        base = os.path.join(self.src, *mod.split("."))
        return next((p for p in (base + ".py", os.path.join(base, "__init__.py")) if os.path.isfile(p)), None)

    def is_module(self, mod: str) -> bool:
        return bool(mod) and self._file(mod) is not None

    def info(self, mod: str) -> dict | None:
        if mod not in self._memo:
            self._memo[mod] = self._load(mod) if self.is_module(mod) else None
        return self._memo[mod]

    def _load(self, mod: str) -> dict:
        path = self._file(mod)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        pkg = mod if path.endswith("__init__.py") else mod.rpartition(".")[0]
        out = {"defined": set(), "imported": {}, "modules": {}}
        stack = list(tree.body)
        while stack:
            st = stack.pop()
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out["defined"].add(st.name)
            elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.For, ast.With)):
                tgts = st.targets if isinstance(st, ast.Assign) else [getattr(st, "target", None)] + \
                    [i.optional_vars for i in getattr(st, "items", [])]
                out["defined"] |= {n.id for t in tgts if t is not None for n in _targets(t) if isinstance(n, ast.Name)}
                stack += getattr(st, "body", []) if isinstance(st, (ast.For, ast.With)) else []
            elif isinstance(st, ast.Import):
                for a in st.names:
                    if self.is_module(a.name):
                        out["modules"][a.asname or a.name] = a.name
            elif isinstance(st, ast.ImportFrom) and (st.level or st.module):
                parts = pkg.split(".") if pkg else []
                base = ".".join((parts[:len(parts) - st.level + 1] if st.level else []) + ([st.module] if st.module else []))
                for a in st.names:
                    if self.is_module(base + "." + a.name if base else a.name):
                        out["modules"][a.asname or a.name] = base + "." + a.name if base else a.name
                    elif self.is_module(base):
                        out["imported"][a.asname or a.name] = (base, a.name)
            elif isinstance(st, (ast.If, ast.Try)) or type(st).__name__ == "TryStar":
                stack += st.body + st.orelse + getattr(st, "finalbody", []) + [x for h in getattr(st, "handlers", []) for x in h.body]
        return out

    def definer(self, mod: str, name: str, hops: int = 0) -> str | None:
        info = self.info(mod)
        if info is None or hops > 8:
            return None
        if name in info["defined"]:
            return mod
        if name in info["imported"]:
            m2, orig = info["imported"][name]
            return self.definer(m2, orig, hops + 1) or m2
        return None


def _import_bound(nodes: list[ast.AST]) -> set[str]:
    out = set()
    for n in nodes:
        if isinstance(n, ast.Import):
            out |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and _name_of(n.value.func) in ("import_module", "__import__"):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return out


def _module_aliases(nodes: list[ast.AST], idx: SrcIndex) -> dict[str, str]:
    out = {}
    for n in nodes:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname and idx.is_module(a.name):
                    out[a.asname] = a.name
                elif not a.asname and idx.is_module(a.name):
                    out[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            out.update({a.asname or a.name: n.module + "." + a.name for a in n.names if idx.is_module(n.module + "." + a.name)})
    return out


def _foreign(chain: list[str], aliases: dict[str, str], idx: SrcIndex) -> str | None:
    mod = aliases.get(chain[0])
    for part in chain[1:-1]:
        if mod and idx.is_module(mod + "." + part):
            mod = mod + "." + part
            continue
        info = idx.info(mod) if mod else None
        mod = info["modules"].get(part) if info else None
    if not mod:
        return None
    d = idx.definer(mod, chain[-1])
    return f"{mod}.{chain[-1]}→{d}" if d and d != mod else None


def _chain(e: ast.AST) -> list[str] | None:
    parts = []
    while isinstance(e, ast.Attribute):
        parts.append(e.attr)
        e = e.value
    return list(reversed(parts + [e.id])) if isinstance(e, ast.Name) else None


def _targets(t: ast.AST):
    if isinstance(t, (ast.Tuple, ast.List)):
        for el in t.elts:
            yield from _targets(el)
    elif isinstance(t, ast.Starred):
        yield from _targets(t.value)
    else:
        yield t


def _mock_patchers(nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    direct, mods = set(), set()
    for n in nodes:
        if isinstance(n, ast.ImportFrom) and n.module in ("unittest.mock", "mock"):
            direct |= {a.asname or a.name for a in n.names if a.name == "patch"}
        elif isinstance(n, ast.ImportFrom) and n.module == "unittest":
            mods |= {a.asname or a.name for a in n.names if a.name == "mock"}
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in ("unittest.mock", "mock") and a.asname:
                    mods.add(a.asname)
                elif a.name in ("mock", "unittest", "unittest.mock"):
                    mods.add("mock" if a.name == "mock" else "unittest")
    return direct, mods


def _is_mock_patch(func: ast.AST, direct: set[str], mods: set[str]) -> bool:
    ch = _chain(func) or []
    if ch and ch[0] in direct:
        return True
    if len(ch) >= 2 and ch[0] in mods and ch[1] == "patch":
        return True
    return len(ch) >= 3 and ch[0] in mods and ch[1] == "mock" and ch[2] == "patch"


def monkeypatches(tree: ast.Module, nodes: list[ast.AST] | None = None, idx: SrcIndex | None = None) -> dict:
    nodes = nodes if nodes is not None else list(ast.walk(tree))
    bound = _import_bound(nodes)
    direct, mods = _mock_patchers(nodes)
    aliases = _module_aliases(nodes, idx) if idx else {}
    attr, call, foreign = [], [], []
    for n in nodes:
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            if isinstance(n, ast.AnnAssign) and n.value is None:
                continue
            for tg in (t for top in (n.targets if isinstance(n, ast.Assign) else [n.target]) for t in _targets(top)):
                is_attr = isinstance(tg, ast.Attribute)
                if is_attr and _root_of(tg) in bound and not (tg.attr == "dont_write_bytecode" and _root_of(tg) == "sys"):
                    attr.append(n.lineno)
                    f = _foreign(_chain(tg), aliases, idx) if idx and _chain(tg) else None
                    if f:
                        foreign.append((n.lineno, f))
                elif isinstance(tg, ast.Subscript) and isinstance(tg.value, ast.Attribute) and tg.value.attr == "modules" \
                        and _root_of(tg.value) == "sys":
                    call.append(n.lineno)
        elif isinstance(n, ast.Call):
            nm = _name_of(n.func)
            if nm in _PATCH_FUNCS:
                call.append(n.lineno)
                if idx and nm == "setattr" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and _chain(n.args[0]):
                    f = _foreign(_chain(n.args[0]) + [str(n.args[1].value)], aliases, idx)
                    if f:
                        foreign.append((n.lineno, f))
            elif _is_mock_patch(n.func, direct, mods):
                call.append(n.lineno)
    return {"attr": sorted(attr), "call": sorted(call), "foreign": sorted(foreign)}
