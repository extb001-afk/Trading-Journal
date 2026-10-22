from __future__ import annotations

import ast
import re

from _arch_hyg_patch import _name_of, _root_of

_READERS = frozenset(["web_src", "core_src", "mod_src", "app_js", "doc_text"])
_ROOTS = frozenset(["SRC", "ROOT", "README", "HERE"])
_ROOT_FUNCS = frozenset(["app_js_path"])
_SEARCH = frozenset(["count", "find", "rfind", "index", "rindex", "startswith", "endswith"])
_RE_SEARCH = frozenset(["search", "match", "fullmatch", "findall", "finditer"])
_RE_TEXT = frozenset(["search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"])
_PASS = frozenset(["str", "list", "sorted", "set", "frozenset", "tuple", "reversed", "iter", "next", "dedent",
                   "get_source_segment", "join"])
_READ_METHODS = frozenset(["read", "read_text", "readlines", "read_bytes"])


_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


_MAY_READ = re.compile(r"\.(?:SRC|ROOT|README|HERE)\b|__file__|web_src|core_src|mod_src|app_js|doc_text|getsource|from _harness import")


def scopes(tree: ast.Module) -> dict[ast.AST, list[ast.AST]]:
    out: dict[ast.AST, list[ast.AST]] = {tree: []}
    stack = [(c, tree) for c in ast.iter_child_nodes(tree)]
    while stack:
        node, owner = stack.pop()
        out[owner].append(node)
        if isinstance(node, _SCOPE):
            out[node] = []
            owner = node
        stack += [(c, owner) for c in ast.iter_child_nodes(node)]
    return out


class _SrcChecks:

    def __init__(self, tree: ast.Module, nodes: list[ast.AST], harness_self: bool = False, sc: dict | None = None):
        self.harness_self = harness_self
        self.harness = {a.asname or a.name for n in nodes if isinstance(n, ast.Import) for a in n.names if a.name == "_harness"}
        self.from_h = {a.asname or a.name: a.name for n in nodes
                       if isinstance(n, ast.ImportFrom) and n.module == "_harness" for a in n.names}
        self.local_fns = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.local_fns |= {t.id for n in nodes if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda)
                           for t in n.targets if isinstance(t, ast.Name)}
        self._root_memo: dict[int, bool] = {}
        self.paths = self._path_names(nodes)
        self.readers = self._reader_helpers(nodes, sc if sc is not None else scopes(tree))
        self.hits: list[int] = []
        self.neg: list[int] = []
        self.depth = 0
        self.ever: set[str] = set()
        self.skip_fns = False
        self.trace: list[set[str]] = []
        self.quiet = 0

    def hit(self, line: int, neg: bool = False) -> None:
        if not self.quiet:
            self.hits.append(line)
            if neg:
                self.neg.append(line)

    def _fixed_root(self, n: ast.AST) -> bool:
        if isinstance(n, ast.Attribute) and (n.attr == "__file__" or
                                             (isinstance(n.value, ast.Name) and n.value.id in self.harness and n.attr in _ROOTS)):
            return True
        if isinstance(n, ast.Name) and (n.id == "__file__" or self.from_h.get(n.id) in _ROOTS or (self.harness_self and n.id in _ROOTS)):
            return True
        return isinstance(n, ast.Call) and _name_of(n.func) in _ROOT_FUNCS

    def mentions_root(self, e: ast.AST) -> bool:
        k = id(e)
        if k not in self._root_memo:
            self._root_memo[k] = any(self._fixed_root(n) or (isinstance(n, ast.Name) and n.id in self.paths)
                                     for n in ast.walk(e))
        return self._root_memo[k]

    def _path_names(self, nodes: list[ast.AST]) -> set[str]:
        facts = []
        for a in nodes:
            if isinstance(a, ast.Assign) and any(isinstance(t, ast.Name) for t in a.targets):
                sub = list(ast.walk(a.value))
                if any(isinstance(n, ast.Call) and _name_of(n.func) in _READ_METHODS for n in sub):
                    continue
                facts.append(({t.id for t in a.targets if isinstance(t, ast.Name)}, any(self._fixed_root(n) for n in sub),
                              {n.id for n in sub if isinstance(n, ast.Name)}))
        paths: set[str] = set()
        while True:
            more = {t for tg, fixed, used in facts if fixed or used & paths for t in tg} - paths
            if not more:
                return paths
            paths |= more

    def _reader_helpers(self, nodes: list[ast.AST], sc: dict[ast.AST, list[ast.AST]]) -> dict[str, bool]:
        out = {}
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name, body = n.name, n
            elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda) and isinstance(n.targets[0], ast.Name):
                name, body = n.targets[0].id, n.value
            else:
                continue
            calls = [c for c in sc.get(body, ()) if isinstance(c, ast.Call)]
            if any(_name_of(c.func) in _READ_METHODS or self._is_reader_call(c) for c in calls):
                out[name] = self.mentions_root(body) or any(self._is_reader_call(c) for c in calls)
        return out

    def _is_reader_call(self, c: ast.Call) -> bool:
        f = c.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in self.harness and f.attr in _READERS:
            return True
        return isinstance(f, ast.Name) and self.from_h.get(f.id) in _READERS or _name_of(f) == "getsource"

    def _read_source(self, c: ast.Call, env: set[str]) -> bool:
        x = c.func.value
        if isinstance(x, ast.Name):
            return ("h:" + x.id) in env or x.id in self.paths
        if isinstance(x, ast.Call) and _name_of(x.func) in ("open", "Path") and x.args:
            return self.mentions_root(x.args[0])
        return self.mentions_root(x)

    def tainted(self, e: ast.AST | None, env: set[str]) -> bool:
        if e is None:
            return False
        if isinstance(e, ast.Name):
            return e.id in env
        if isinstance(e, ast.Call):
            return self._call_tainted(e, env)
        if isinstance(e, (ast.Subscript, ast.Attribute, ast.Starred, ast.FormattedValue, ast.NamedExpr, ast.Await)):
            return self.tainted(e.value, env)
        if isinstance(e, ast.BinOp):
            return self.tainted(e.left, env) or self.tainted(e.right, env)
        if isinstance(e, ast.BoolOp):
            return any(self.tainted(v, env) for v in e.values)
        if isinstance(e, ast.IfExp):
            return self.tainted(e.body, env) or self.tainted(e.orelse, env)
        if isinstance(e, (ast.JoinedStr, ast.List, ast.Tuple, ast.Set)):
            return any(self.tainted(v, env) for v in (e.values if isinstance(e, ast.JoinedStr) else e.elts))
        if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self.tainted(e.elt, self._comp_env(e, env, count=False))
        if isinstance(e, ast.DictComp):
            return self.tainted(e.value, self._comp_env(e, env, count=False))
        if isinstance(e, ast.Dict):
            return any(self.tainted(v, env) for v in e.values)
        return False

    def _call_tainted(self, c: ast.Call, env: set[str]) -> bool:
        f, nm = c.func, _name_of(c.func)
        args = list(c.args) + [k.value for k in c.keywords]
        if self._is_reader_call(c):
            return True
        if isinstance(f, ast.Attribute) and nm in _READ_METHODS and self._read_source(c, env):
            return True
        if isinstance(f, ast.Name) and f.id in self.readers:
            return self.readers[f.id] or any(self.mentions_root(a) for a in args)
        if isinstance(f, ast.Attribute) and nm not in _SEARCH and self.tainted(f.value, env):
            return True
        if isinstance(f, ast.Attribute) and _root_of(f) == "re" and nm in _RE_TEXT:
            return any(self.tainted(a, env) for a in args)
        if nm in _PASS or (isinstance(f, ast.Name) and f.id in self.local_fns):
            return any(self.tainted(a, env) for a in args)
        return False

    def _comp_env(self, e: ast.AST, env: set[str], count: bool) -> set[str]:
        inner = set(env)
        for g in e.generators:
            if count:
                self.count(g.iter, inner)
            self._bind(g.target, self.tainted(g.iter, inner), inner)
            for cond in g.ifs:
                if count:
                    self.count(cond, inner)
        return inner

    def count(self, e: ast.AST | None, env: set[str]) -> None:
        if e is None:
            return
        if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            inner = self._comp_env(e, env, count=True)
            for part in ((e.key, e.value) if isinstance(e, ast.DictComp) else (e.elt,)):
                self.count(part, inner)
            return
        if isinstance(e, ast.Compare):
            for op, right in zip(e.ops, e.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and self.tainted(right, env):
                    self.hit(e.lineno, isinstance(op, ast.NotIn))
        elif isinstance(e, ast.Call):
            f, nm = e.func, _name_of(e.func)
            if isinstance(f, ast.Attribute) and nm in _SEARCH and self.tainted(f.value, env):
                self.hit(e.lineno)
            elif isinstance(f, ast.Attribute) and nm in _RE_SEARCH and not self.tainted(f.value, env) \
                    and any(self.tainted(a, env) for a in list(e.args) + [k.value for k in e.keywords]):
                self.hit(e.lineno)
        elif isinstance(e, ast.NamedExpr):
            self.count(e.value, env)
            self._bind(e.target, self.tainted(e.value, env), env)
            return
        for child in ast.iter_child_nodes(e):
            if isinstance(child, ast.expr):
                self.count(child, env)
            elif isinstance(child, ast.keyword):
                self.count(child.value, env)

    def _bind(self, target: ast.AST, t: bool, env: set[str], value: ast.AST | None = None) -> None:
        if isinstance(target, ast.Name):
            (env.add if t else env.discard)(target.id)
            if t and self.depth == 0:
                self.ever.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            same = isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts)
            ts = [self.tainted(v, env) for v in value.elts] if same else [t] * len(target.elts)
            for el, ti in zip(target.elts, ts):
                self._bind(el, ti, env)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, t, env)

    def _loop(self, st: ast.stmt, env: set[str]) -> None:
        if not isinstance(st, ast.While):
            self.count(st.iter, env)

        def one_pass(entry: set[str]) -> set[str]:
            body = set(entry)
            if not isinstance(st, ast.While):
                it = st.iter
                self._bind(st.target, self.tainted(it, entry) or (isinstance(it, ast.Name) and ("h:" + it.id) in entry), body)
            self.run(st.body, body)
            return body
        entry = set(env)
        self.quiet += 1
        names = {n.id for x in st.body for n in ast.walk(x) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        for _ in range(len(names) + 2):
            grown = entry | one_pass(entry)
            if grown == entry:
                break
            entry = grown
        self.quiet -= 1
        if isinstance(st, ast.While):
            self.count(st.test, entry)
        body = one_pass(entry)
        after = env | body
        exit_break = set(after) if _has_break(st.body) else set()
        self.run(st.orelse, after)
        env.clear()
        env.update(after | exit_break)

    def _try(self, st: ast.stmt, env: set[str]) -> None:
        before = set(env)
        body = set(env)
        self.trace.append(set(before))
        self.run(st.body, body)
        seen = self.trace.pop()
        if self.trace:
            self.trace[-1] |= seen
        self.run(st.orelse, body)
        outs = [body]
        self.trace.append(set())
        for h in st.handlers:
            he = before | seen | body
            if h.name:
                he.discard(h.name)
            self.run(h.body, he)
            outs.append(he)
        seen |= self.trace.pop()
        merged = set().union(*outs)
        if st.finalbody:
            self.run(st.finalbody, merged | seen)
            self.quiet += 1
            self.run(st.finalbody, merged)
            self.quiet -= 1
        env.clear()
        env.update(merged)

    def run(self, stmts: list[ast.stmt], env: set[str]) -> None:
        for st in stmts:
            self._stmt(st, env)
            if self.trace:
                self.trace[-1] |= env

    def _stmt(self, st: ast.stmt, env: set[str]) -> None:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in st.decorator_list:
                self.count(d, env)
            if not self.skip_fns:
                self.depth += 1
                saved, self.trace = self.trace, []
                self.run(st.body, set(env) | self.ever)
                self.trace = saved
                self.depth -= 1
        elif isinstance(st, ast.ClassDef):
            for d in st.decorator_list:
                self.count(d, env)
            self.run(st.body, set(env))
        elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            self.count(st.value, env)
            t = self.tainted(st.value, env)
            for tg in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                if isinstance(st, ast.AugAssign) and isinstance(tg, ast.Name) and tg.id in env:
                    continue
                if st.value is not None:
                    self._bind(tg, t, env, st.value)
        elif isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
            self._loop(st, env)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                self.count(item.context_expr, env)
                ce, var = item.context_expr, item.optional_vars
                if isinstance(var, ast.Name):
                    src = isinstance(ce, ast.Call) and _name_of(ce.func) == "open" and bool(ce.args) and self.mentions_root(ce.args[0])
                    (env.add if src else env.discard)("h:" + var.id)
                    self._bind(var, self.tainted(ce, env), env)
            self.run(st.body, env)
        elif isinstance(st, ast.If):
            self.count(st.test, env)
            a, b = set(env), set(env)
            self.run(st.body, a)
            self.run(st.orelse, b)
            env.clear()
            env.update(a | b)
        elif isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
            self._try(st, env)
        else:
            for child in ast.iter_child_nodes(st):
                if isinstance(child, ast.expr):
                    self.count(child, env)


def _has_break(stmts: list[ast.stmt]) -> bool:
    stack = list(stmts)
    while stack:
        st = stack.pop()
        if isinstance(st, ast.Break):
            return True
        if isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack += st.orelse if isinstance(st, (ast.For, ast.AsyncFor, ast.While)) else []
            continue
        for block in ("body", "orelse", "finalbody"):
            stack += [x for x in getattr(st, block, None) or [] if isinstance(x, ast.stmt)]
        stack += [x for h in getattr(st, "handlers", None) or [] for x in h.body]
        stack += [x for c in getattr(st, "cases", None) or [] for x in c.body]
    return False


def source_checks(tree: ast.Module, nodes: list[ast.AST] | None = None, harness_self: bool = False,
                  sc: dict | None = None) -> tuple[list[int], list[int]]:
    a = _SrcChecks(tree, nodes if nodes is not None else list(ast.walk(tree)), harness_self, sc)
    a.skip_fns = True
    a.run(tree.body, set())
    a.skip_fns, a.hits, a.neg = False, [], []
    a.run(tree.body, set())
    return sorted(a.hits), sorted(a.neg)
