from __future__ import annotations

import ast

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMP = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPE_T = _FUNC + (ast.Lambda, ast.ClassDef) + _COMP


class _Scope:
    def __init__(self, kind, q, prefix, parent):
        self.kind, self.q, self.prefix, self.parent = kind, q, prefix, parent
        self.b, self.glob, self.nonloc, self.nodes, self.kids = {}, set(), set(), [], []
        self.cpos = {}
        self.cur = None

    def add(self, name, tag):
        self.b.setdefault(name, set()).add(tag)
        if self.kind == "class" and self.cur is not None:
            self.cpos.setdefault(name, []).append(self.cur + (tag,))

    def module(self):
        s = self
        while s.parent is not None:
            s = s.parent
        return s

    def target(self, name):
        if name in self.glob:
            return self.module()
        if name in self.nonloc:
            s, first_fn = self.parent, None
            while s is not None and s.kind != "module":
                if s.kind == "function":
                    first_fn = first_fn or s
                    if name in s.b and name not in s.nonloc:
                        return s
                s = s.parent
            return first_fn or self
        return self


def _parts(node):
    if isinstance(node, _FUNC):
        a = node.args
        ann = [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if x is not None and x.annotation]
        outer = list(node.decorator_list) + list(a.defaults) + [d for d in a.kw_defaults if d is not None] + ann
        return outer + ([node.returns] if node.returns else []), list(node.body)
    if isinstance(node, ast.Lambda):
        a = node.args
        return list(a.defaults) + [d for d in a.kw_defaults if d is not None], [node.body]
    if isinstance(node, ast.ClassDef):
        return list(node.decorator_list) + list(node.bases) + list(node.keywords), list(node.body)
    g0, rest = node.generators[0], list(node.generators[1:])
    inner = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    return [g0.iter], inner + [g0.target] + list(g0.ifs) + rest


def _shallow(nodes):
    stack = list(reversed(nodes))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, SCOPE_T):
            stack.extend(reversed(_parts(n)[0]))
        else:
            stack.extend(reversed(list(ast.iter_child_nodes(n))))


def _walrus_home(sc):
    s = sc
    while s.kind == "comp" and s.parent is not None:
        s = s.parent
    return s


def _bind(n, sc):
    if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
        n.target._walrus = True
        home = _walrus_home(sc)
        home.target(n.target.id).add(n.target.id, ("other",))
    elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
        if not getattr(n, "_walrus", False):
            sc.target(n.id).add(n.id, ("other",))
    elif isinstance(n, ast.Import):
        for a in n.names:
            name, mod = (a.asname, a.name) if a.asname else (a.name.split(".")[0], a.name.split(".")[0])
            sc.target(name).add(name, ("mod", mod))
    elif isinstance(n, ast.ImportFrom):
        mod = ("." * (n.level or 0)) + (n.module or "")
        for a in n.names:
            if a.name != "*":
                sc.target(a.asname or a.name).add(a.asname or a.name, ("from", mod, a.name))
    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        sc.target(n.name).add(n.name, ("other",))
    elif isinstance(n, ast.ExceptHandler) and n.name:
        sc.target(n.name).add(n.name, ("other",))
    else:
        for f in ("name", "rest"):
            v = getattr(n, f, None) if type(n).__name__ in ("MatchAs", "MatchStar", "MatchMapping") else None
            if isinstance(v, str):
                sc.target(v).add(v, ("other",))


def _tag(s, x):
    tags = s.b[x]
    if len(tags) == 1:
        t = next(iter(tags))
        if t[0] in ("mod", "from"):
            return t
        return ("global",) if s.kind == "module" else ("local",)
    return ("amb", tuple(sorted({":".join(t) for t in tags})))


def _class_lookup(x, s, at):
    outer = _resolve(x, s.parent, first=False)[0]
    before = [b for b in s.cpos.get(x, []) if at is not None and b[0] < at]
    if not before:
        return outer
    last = max(b[0] for b in before)
    lasts = [b for b in before if b[0] == last]
    if all(b[1] for b in lasts) and len({b[2] for b in lasts}) == 1:
        t = lasts[0][2]
        return t if t[0] in ("mod", "from") else ("local",)
    descs = {":".join(b[2]) for b in before} | (set(outer[1]) if outer[0] == "amb" else {":".join(outer)})
    return ("amb", tuple(sorted(descs)))


def _resolve(x, sc, first=True, at=None):
    s = sc
    while s is not None:
        if s.kind == "class" and not first:
            s = s.parent
            continue
        if x in s.glob:
            m = s.module()
            return (_tag(m, x), m.kind) if x in m.b else (("unbound",), None)
        if x in s.nonloc:
            first, s = False, s.parent
            continue
        if x in s.b:
            if s.kind == "class":
                return _class_lookup(x, s, at), s.kind
            return _tag(s, x), s.kind
        first, s = False, s.parent
    return ("unbound",), None


def _child(n, sc):
    if isinstance(n, _FUNC):
        q = n.name if sc.kind == "module" else (sc.prefix + "." + n.name if sc.prefix else n.name)
        new = _Scope("function", q, q, sc)
    elif isinstance(n, ast.ClassDef):
        pre = n.name if sc.kind == "module" else (sc.prefix + "." + n.name if sc.prefix else n.name)
        new = _Scope("class", pre + ".<body>", pre, sc)
    else:
        new = _Scope("comp" if isinstance(n, _COMP) else "function", sc.q, sc.prefix, sc)
    if isinstance(n, _FUNC + (ast.Lambda,)):
        a = n.args
        for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
            if x is not None:
                new.add(x.arg, ("other",))
    return new


_UNCOND = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
           ast.ClassDef, ast.Expr, ast.Pass)


def _build(nodes, sc):
    nodes = list(nodes)
    sc.nodes = list(_shallow(nodes))
    for n in sc.nodes:
        if isinstance(n, ast.Global):
            sc.glob.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            sc.nonloc.update(n.names)
    if sc.kind == "class":
        for i, st in enumerate(nodes):
            sc.cur = (i, isinstance(st, _UNCOND))
            for n in _shallow([st]):
                n._ci = i
                _bind(n, sc)
        sc.cur = None
    else:
        for n in sc.nodes:
            _bind(n, sc)
    for n in sc.nodes:
        if isinstance(n, SCOPE_T):
            kid = _child(n, sc)
            sc.kids.append(kid)
            _build(_parts(n)[1], kid)


def _resolve_all(sc):
    for n in sc.nodes:
        if isinstance(n, ast.Name) and sc.kind == "class" and not isinstance(n.ctx, ast.Load) \
                and n.id not in sc.glob and n.id not in sc.nonloc:
            n._r, n._rs = ("local",), "class"
        elif isinstance(n, ast.Name):
            n._r, n._rs = _resolve(n.id, sc, at=getattr(n, "_ci", None) if sc.kind == "class" else None)
        if isinstance(n, ast.Name):
            n._q = sc.q
    for kid in sc.kids:
        _resolve_all(kid)


def annotate(tree):
    root = _Scope("module", "<module>", "", None)
    _build(tree.body, root)
    _resolve_all(root)
    for st in tree.body:
        top = st.name if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "<module>"
        for n in ast.walk(st):
            if isinstance(n, ast.Name):
                n._top = top
    return tree
