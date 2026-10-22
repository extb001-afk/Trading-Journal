from __future__ import annotations

import ast
import os
import re
import textwrap

import _core_bounds as B

_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
EMBED_SKIP = frozenset(["tests/test_svc_names.py", "tests/test_core_svc_codemod.py", "tests/test_core_bounds.py"])

SVC_ATTR = {"svc_exf": "EXF", "svc_recon": "RECON", "svc_price": "PRICING"}
SVC_CLS = {"ExfService": "EXF", "ReconService": "RECON", "PriceService": "PRICING"}
RECV = ("inst", "bare", "plan", "cls")


def _any_recv(ks):
    return any(k in RECV or k.startswith(("svc:", "svccls:")) for k in ks)


def owned_names(fx):
    out, clash = {}, set()

    def put(n, g):
        if n.startswith("__"):
            return
        if n in out and out[n] != g:
            clash.add(n)
        out[n] = g
    for n, c in fx["owner"].items():
        g = fx["classes"][c]["group"]
        if g in B.GROUPS_SVC:
            put(n, g)
    for n, gs in fx["state_all"].items():
        rest = [g for g in gs if g != "CORE"] if n in fx["core_init_only"] else list(gs)
        if len(rest) == 1 and rest[0] in B.GROUPS_SVC:
            put(n, rest[0])
    for n in clash:
        out.pop(n, None)
    return out


class Scope:
    def __init__(self, node, parent, kind, qual):
        self.node, self.parent, self.kind, self.qual = node, parent, kind, qual
        self.binds = {}
        self.globals = set()

    def bind(self, name, val):
        tgt = self
        if name in self.globals:
            while tgt.parent is not None:
                tgt = tgt.parent
        tgt.binds.setdefault(name, []).append(val)


def _targets(t, val, out):
    if isinstance(t, ast.Name):
        out.append((t.id, val))
    elif isinstance(t, (ast.Tuple, ast.List)):
        for i, e in enumerate(t.elts):
            if val[0] == "expr" and isinstance(val[1], (ast.Tuple, ast.List)) and len(val[1].elts) == len(t.elts):
                _targets(e, ("expr", val[1].elts[i]), out)
            elif val[0] == "iter":
                _targets(e, ("iterelt", val[1], i), out)
            else:
                _targets(e, ("other",), out)
    elif isinstance(t, ast.Starred):
        _targets(t.value, ("other",), out)


class Resolver(ast.NodeVisitor):

    def __init__(self, tree):
        self.mod_alias, self.cls_alias, self.svc_alias = set(), set(), set()
        for x in ast.walk(tree):
            if isinstance(x, ast.Import):
                for a in x.names:
                    if a.name == "core":
                        self.mod_alias.add(a.asname or "core")
                    elif a.name == "core_svc":
                        self.svc_alias.add(a.asname or "core_svc")
            elif isinstance(x, ast.ImportFrom) and x.module == "core" and not x.level:
                for a in x.names:
                    if a.name == "Core":
                        self.cls_alias.add(a.asname or "Core")
        self.root = Scope(tree, None, "module", "<module>")
        self.tree, self._callmap = tree, None
        self._parent = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        self._memo, self._busy = {}, set()
        self.scope_of = {}
        self.funcs = {}
        self.stack = [self.root]
        self.visit(tree)

    def _push(self, node, kind, name):
        par = self.stack[-1]
        q = name if par.kind == "module" else "%s.%s" % (par.qual, name)
        s = Scope(node, par, kind, q)
        self.stack.append(s)
        return s

    def generic_visit(self, node):
        self.scope_of[id(node)] = self.stack[-1]
        super().generic_visit(node)

    def visit_FunctionDef(self, node):
        self.scope_of[id(node)] = self.stack[-1]
        self.stack[-1].bind(node.name, ("func", node))
        for d in node.decorator_list + node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(d)
        s = self._push(node, "func", node.name)
        self.funcs[id(node)] = s
        a = node.args
        pos = a.posonlyargs + a.args
        plain = self.stack[-2].kind in ("module", "func")
        for i, p in enumerate(pos):
            s.bind(p.arg, ("param", node, i, p.arg) if plain else ("other",))
        for p in a.kwonlyargs:
            s.bind(p.arg, ("param", node, None, p.arg) if plain else ("other",))
        for p in ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
            s.bind(p.arg, ("other",))
        for b in node.body:
            self.visit(b)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Global(self, node):
        self.stack[-1].globals |= set(node.names)

    def visit_Lambda(self, node):
        self.scope_of[id(node)] = self.stack[-1]
        s = self._push(node, "func", "<lambda>")
        for p in node.args.args:
            s.bind(p.arg, ("other",))
        self.visit(node.body)
        self.stack.pop()

    def visit_ClassDef(self, node):
        self.scope_of[id(node)] = self.stack[-1]
        self.stack[-1].bind(node.name, ("other",))
        for b in node.bases + node.decorator_list:
            self.visit(b)
        self._push(node, "class", node.name)
        for b in node.body:
            self.visit(b)
        self.stack.pop()

    def _comp(self, node):
        self.scope_of[id(node)] = self.stack[-1]
        self.visit(node.generators[0].iter)
        par = self.stack[-1]
        s = Scope(node, par, "comp", par.qual)
        self.stack.append(s)
        for i, g in enumerate(node.generators):
            for nm, v in _bind_list(g.target, ("iter", g.iter)):
                s.bind(nm, v)
            if i:
                self.visit(g.iter)
            for c in g.ifs:
                self.visit(c)
        for e in ([node.elt] if hasattr(node, "elt") else [node.key, node.value]):
            self.visit(e)
        self.stack.pop()

    visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _comp

    def visit_Assign(self, node):
        for t in node.targets:
            for nm, v in _bind_list(t, ("expr", node.value)):
                self.stack[-1].bind(nm, v)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            for nm, v in _bind_list(node.target, ("expr", node.value)):
                self.stack[-1].bind(nm, v)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        for nm, v in _bind_list(node.target, ("other",)):
            self.stack[-1].bind(nm, v)
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        s = self.stack[-1]
        while s.kind == "comp":
            s = s.parent
        s.bind(node.target.id, ("expr", node.value))
        self.generic_visit(node)

    def visit_For(self, node):
        for nm, v in _bind_list(node.target, ("iter", node.iter)):
            self.stack[-1].bind(nm, v)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for it in node.items:
            if it.optional_vars is not None:
                for nm, v in _bind_list(it.optional_vars, ("other",)):
                    self.stack[-1].bind(nm, v)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node):
        if node.name:
            self.stack[-1].bind(node.name, ("other",))
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            self.stack[-1].bind((a.asname or a.name).split(".")[0], ("module", a.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for a in node.names:
            self.stack[-1].bind(a.asname or a.name, ("from", node.module, a.name))
        self.generic_visit(node)

    def lookup(self, name, scope):
        s, first = scope, True
        while s is not None:
            if s.kind != "class" or first:
                if name in s.binds:
                    return s
            first = False
            s = s.parent
        return None

    def name_kind(self, name, scope, seen=None):
        s = self.lookup(name, scope)
        if s is None:
            return "other"
        key = (id(s), name)
        if key in self._memo:
            return self._memo[key]
        if key in self._busy:
            return "other"
        self._busy.add(key)
        kinds = {self._val_kind(v, s, set()) for v in s.binds[name]}
        self._busy.discard(key)
        if len(kinds) == 1:
            out = kinds.pop()
        else:
            out = "mixed" if _any_recv(kinds) else "other"
        self._memo[key] = out
        return out

    def _val_kind(self, v, s, seen):
        if v[0] == "expr":
            return self.expr_kind(v[1], s, seen)
        if v[0] == "iter":
            it = v[1]
            if isinstance(it, (ast.Tuple, ast.List)) and it.elts:
                ks = {self.expr_kind(e, s, seen) for e in it.elts}
                return ks.pop() if len(ks) == 1 else ("mixed" if _any_recv(ks) else "other")
            return "other"
        if v[0] == "iterelt":
            it = v[1]
            if isinstance(it, (ast.Tuple, ast.List)) and it.elts and all(isinstance(e, (ast.Tuple, ast.List)) and len(e.elts) > v[2] for e in it.elts):
                ks = {self.expr_kind(e.elts[v[2]], s, seen) for e in it.elts}
                return ks.pop() if len(ks) == 1 else ("mixed" if _any_recv(ks) else "other")
            return "other"
        if v[0] == "from" and v[1] == "core" and v[2] == "Core":
            return "cls"
        if v[0] == "from" and v[1] == "core_svc" and v[2] in SVC_CLS:
            return "svccls:" + SVC_CLS[v[2]]
        if v[0] == "func":
            return "func"
        if v[0] == "param":
            return self._param_kind(v[1], v[2], v[3])
        return "other"

    def _calls_of(self, fn):
        if self._callmap is None:
            self._callmap, esc = {}, set()
            for x in ast.walk(self.tree):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
                    sc = self.scope_of.get(id(x))
                    s = self.lookup(x.id, sc) if sc else None
                    vals = s.binds[x.id] if s else []
                    if len(vals) == 1 and vals[0][0] == "func":
                        par = self._parent.get(id(x))
                        if isinstance(par, ast.Call) and par.func is x:
                            self._callmap.setdefault(id(vals[0][1]), []).append(par)
                        else:
                            esc.add(id(vals[0][1]))
            for k in esc:
                self._callmap[k] = None
        return self._callmap.get(id(fn), [])

    def _param_kind(self, fn, i, name):
        calls = self._calls_of(fn)
        if not calls:
            return "other"
        ks = set()
        for c in calls:
            arg = None
            if i is not None and not any(isinstance(a, ast.Starred) for a in c.args[:i + 1]) and len(c.args) > i:
                arg = c.args[i]
            else:
                arg = next((k.value for k in c.keywords if k.arg == name), None)
            if arg is None:
                return "other"
            ks.add(self.expr_kind(arg, self.scope_of.get(id(c)) or self.root))
        if len(ks) == 1:
            return ks.pop()
        return "mixed" if _any_recv(ks) else "other"

    def is_cls(self, e, scope, seen=None):
        if isinstance(e, ast.Attribute) and e.attr == "Core" and isinstance(e.value, ast.Name) and e.value.id in self.mod_alias:
            return True
        if isinstance(e, ast.Name):
            if e.id in self.cls_alias and self.lookup(e.id, scope) is None:
                return True
            return self.name_kind(e.id, scope, seen) == "cls"
        return False

    def expr_kind(self, e, scope, seen=None):
        seen = set() if seen is None else seen
        if self.is_cls(e, scope, seen):
            return "cls"
        if isinstance(e, ast.Attribute) and e.attr in SVC_ATTR and self.expr_kind(e.value, scope, seen) in ("inst", "bare"):
            return "svc:" + SVC_ATTR[e.attr]
        if isinstance(e, ast.Attribute) and e.attr in SVC_CLS and isinstance(e.value, ast.Name) and e.value.id in self.svc_alias:
            return "svccls:" + SVC_CLS[e.attr]
        if isinstance(e, ast.Name):
            return self.name_kind(e.id, scope, seen)
        if isinstance(e, ast.IfExp):
            a, b = self.expr_kind(e.body, scope, seen), self.expr_kind(e.orelse, scope, seen)
            return a if a == b else ("mixed" if _any_recv({a, b}) else "other")
        if isinstance(e, ast.Call):
            f = e.func
            if self.is_cls(f, scope, seen):
                return "inst"
            if isinstance(f, ast.Attribute) and f.attr in ("__new__", "settle_planner") and self.is_cls(f.value, scope, seen):
                return "bare" if f.attr == "__new__" else "plan"
            if isinstance(f, ast.Attribute) and f.attr == "__new__" and isinstance(f.value, ast.Name) and f.value.id == "object" \
                    and e.args and self.is_cls(e.args[0], scope, seen):
                return "bare"
            if isinstance(f, ast.Name):
                s = self.lookup(f.id, scope)
                if s is not None:
                    fns = [v[1] for v in s.binds[f.id] if v[0] == "func"]
                    if len(fns) == 1 and len(s.binds[f.id]) == 1:
                        return self._returns_kind(fns[0], seen)
        return "other"

    def _returns_kind(self, fn, seen):
        key = ("ret", id(fn))
        if key in seen:
            return "other"
        seen.add(key)
        fs = self.funcs.get(id(fn))
        rets = [x for x in ast.walk(fn) if isinstance(x, ast.Return) and self._owner_func(x) is fn]
        ks = {self.expr_kind(r.value, fs, seen) if r.value is not None else "other" for r in rets}
        return ks.pop() if len(ks) == 1 and _any_recv(ks) and "cls" not in ks and not any(k.startswith("svccls:") for k in ks) else "other"

    def _owner_func(self, node):
        s = self.scope_of.get(id(node))
        while s is not None and s.kind not in ("func", "module"):
            s = s.parent
        return s.node if s is not None else None

    def key_strings(self, e, scope):
        c = B._const_str(e)
        if c is not None:
            return [c]
        if not isinstance(e, ast.Name):
            return None
        s = self.lookup(e.id, scope)
        if s is None:
            return None
        out = []
        for v in s.binds[e.id]:
            it = v[1] if v[0] in ("iter", "expr") else None
            if v[0] == "iter" and isinstance(it, ast.Name):
                s2 = self.lookup(it.id, s)
                cands = [w[1] for w in (s2.binds[it.id] if s2 else []) if w[0] == "expr"]
                it = cands[0] if len(cands) == 1 else None
            if v[0] == "iter" and isinstance(it, (ast.Tuple, ast.List, ast.Set)) and all(B._const_str(x) is not None for x in it.elts):
                out += [x.value for x in it.elts]
            elif v[0] == "expr" and B._const_str(it) is not None:
                out.append(it.value)
            else:
                return None
        return list(dict.fromkeys(out)) or None


def _bind_list(t, val):
    out = []
    _targets(t, val, out)
    return out


def scan_file(path, owned, file_key=None):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if "Core" not in text and not (set(_WORD.findall(text)) & owned.keys()):
        return []
    return scan_tree_ast(ast.parse(text, path), owned, file_key or path)


def scan_tree_ast(tree, owned, file_key, reads_unresolved=False):
    R = Resolver(tree)
    out = []

    def add(cat, name, node, recv=None, rk=None, how=None):
        sc = R.scope_of.get(id(node)) or R.root
        out.append({"cat": cat, "group": owned.get(name, "?"), "name": name, "line": node.lineno, "col": node.col_offset,
                    "scope": sc.qual, "recv": recv, "rk": rk, "node": node, "how": how, "file": file_key})

    def rkind(e, node):
        sc = R.scope_of.get(id(node)) or R.root
        k = R.expr_kind(e, sc)
        return k if k in RECV else None

    def skind(e, node):
        k = R.expr_kind(e, R.scope_of.get(id(node)) or R.root)
        return k.split(":")[1] if k.startswith(("svc:", "svccls:")) else None

    for x in ast.walk(tree):
        if isinstance(x, ast.Attribute) and x.attr in owned:
            k = rkind(x.value, x)
            sg = None if k else skind(x.value, x)
            if sg:
                if owned[x.attr] != sg:
                    add("svc_mismatch", x.attr, x, x.value, None, "attr")
            elif k:
                cat = "assign" if isinstance(x.ctx, ast.Store) else ("del" if isinstance(x.ctx, ast.Del) else "read")
                add(cat, x.attr, x, x.value, k, "attr")
                p = R._parent.get(id(x))
                if k == "cls" and isinstance(p, ast.Call) and p.func is x \
                        and any(rkind(a, p) for a in list(p.args) + [kw.value for kw in p.keywords]):
                    out[-1]["self_arg"] = True
            elif isinstance(x.ctx, (ast.Store, ast.Del)):
                add("assign?" if isinstance(x.ctx, ast.Store) else "del?", x.attr, x, x.value, None, "attr")
            elif reads_unresolved and (R.mod_alias or R.cls_alias):
                add("read?", x.attr, x, x.value, None, "attr")
        elif isinstance(x, ast.Call):
            f = x.func
            fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if fname in ("hasattr", "getattr", "setattr", "delattr") and isinstance(f, ast.Name) and len(x.args) >= 2:
                _str_site(x, x.args[0], x.args[1], "probe" if fname in ("hasattr", "getattr") else "indirect", fname, owned, R, add, rkind)
            elif fname == "patch_cls_attr" and len(x.args) >= 2:
                _str_site(x, x.args[0], x.args[1], "indirect", fname, owned, R, add, rkind)
            elif fname == "object" and isinstance(f, ast.Attribute) and ast.unparse(f).endswith("patch.object") and len(x.args) >= 2:
                _str_site(x, x.args[0], x.args[1], "indirect", "patch.object", owned, R, add, rkind)
            elif fname == "patch_moved" and x.args:
                ks = R.key_strings(x.args[0], R.scope_of.get(id(x)) or R.root)
                for k in ks or []:
                    if k in owned:
                        add("patch_moved", k, x, None, None, "patch_moved")
            elif fname in B.DICT_METH and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == "__dict__" and x.args:
                _str_site(x, f.value.value, x.args[0], "indirect", "__dict__." + fname, owned, R, add, rkind)
        elif isinstance(x, ast.Subscript) and isinstance(x.value, ast.Attribute) and x.value.attr == "__dict__":
            _str_site(x, x.value.value, x.slice, "indirect", "__dict__[]", owned, R, add, rkind)
        elif isinstance(x, ast.Compare) and len(x.comparators) == 1 and isinstance(x.ops[0], (ast.In, ast.NotIn)) \
                and isinstance(x.comparators[0], ast.Attribute) and x.comparators[0].attr == "__dict__":
            _str_site(x, x.comparators[0].value, x.left, "indirect", "in __dict__", owned, R, add, rkind)
        elif isinstance(x, ast.ClassDef):
            sc = R.scope_of.get(id(x)) or R.root
            if any(R.is_cls(b, sc) for b in x.bases):
                for b in x.body:
                    nms = [b.name] if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) else \
                        [t.id for t in getattr(b, "targets", []) if isinstance(t, ast.Name)]
                    for n in nms:
                        if n in owned:
                            add("subclass", n, b, None, None, "subclass")
    for x in (ast.walk(tree) if file_key not in EMBED_SKIP else ()):
        if isinstance(x, ast.Constant) and isinstance(x.value, str) and ("import core" in x.value or "from core" in x.value):
            try:
                sub = ast.parse(textwrap.dedent(x.value))
            except SyntaxError:
                continue
            sc = R.scope_of.get(id(x)) or R.root
            for e in scan_tree_ast(sub, owned, file_key):
                e.update(line=x.lineno, col=x.col_offset, scope=sc.qual + "<글>", embedded=True)
                out.append(e)
    out.sort(key=lambda r: (r["line"], r["col"], r["cat"], r["name"]))
    return out


def _str_site(call, recv, key, cat, how, owned, R, add, rkind):
    sc = R.scope_of.get(id(call)) or R.root
    k = rkind(recv, call)
    ks = R.key_strings(key, sc)
    sk = R.expr_kind(recv, sc)
    if not k and sk.startswith(("svc:", "svccls:")):
        if ks is None:
            add("key?", "?", call, recv, None, how)
        for s9 in ks or []:
            if s9 in owned and owned[s9] != sk.split(":")[1]:
                add("svc_mismatch", s9, call, recv, None, how)
        return
    if ks is None:
        if k:
            add("key?", "?", call, recv, k, how)
        return
    for s in ks:
        if s in owned:
            if k:
                add(cat, s, call, recv, k, how + ("" if B._const_str(key) is not None else "(변수 열쇠)"))
            else:
                add(cat + "?", s, call, recv, None, how)


def tree_files(root):
    out = []
    src = os.path.join(root, "src")
    for f in sorted(os.listdir(src)):
        if f.endswith(".py") and not f.startswith("core"):
            out.append(("src/" + f, os.path.join(src, f)))
    tools = os.path.join(root, "tools")
    if os.path.isdir(tools):
        for dp, dn, fn in os.walk(tools):
            dn[:] = sorted(d for d in dn if d != "__pycache__")
            for f in sorted(fn):
                if f.endswith(".py"):
                    p = os.path.join(dp, f)
                    out.append(("tools/" + os.path.relpath(p, tools).replace(os.sep, "/"), p))
    tests = os.path.join(root, "public", "tests")
    if not os.path.isdir(tests):
        tests = os.path.join(root, "tests")
    for f in sorted(os.listdir(tests)):
        if f.endswith(".py"):
            out.append(("tests/" + f, os.path.join(tests, f)))
    return out


def scan_tree(root, owned):
    sites = []
    for key, p in tree_files(root):
        try:
            sites += scan_file(p, owned, key)
        except SyntaxError as e:
            sites.append({"cat": "parse?", "group": "?", "name": str(e)[:60], "line": 0, "col": 0, "scope": "<module>",
                          "recv": None, "rk": None, "node": None, "how": None, "file": key})
    return sites


def counts(sites):
    out = {}
    for s in sites:
        k = (s["file"], s["scope"], s["cat"], s["group"], s["name"])
        out[k] = out.get(k, 0) + 1
    return out


def judge(sites, table, present):
    cur = counts(sites)
    base = {tuple(r[:5]): r[5] for r in table.get("findings", [])}
    allow = {tuple(a["key"]) for a in table.get("allow", [])}
    enf = {g for g, on in (table.get("enforce") or {}).items() if on}
    bad, lower = [], []
    for k, n in sorted(cur.items()):
        if k in allow:
            continue
        if k[3] in enf or (enf and k[3] == "?"):
            bad.append("묶음 %s 0 강제: %s ×%d" % (k[3] if k[3] != "?" else "(못 정함)", "|".join(k), n))
        elif k not in base:
            bad.append("표 밖 새 자리 %s ×%d" % ("|".join(k), n))
        elif n > base[k]:
            bad.append("자리 늘어남 %s %d → %d" % ("|".join(k), base[k], n))
    for k, n in sorted(base.items()):
        if k[0] in present and cur.get(k, 0) < n:
            lower.append("줄어듦 %s %d → %d" % ("|".join(k), n, cur.get(k, 0)))
    return bad, lower


def table_from(sites, old):
    cur = counts(sites)
    return {"_doc": old.get("_doc", ""), "enforce": old.get("enforce", {g: False for g in B.GROUPS_SVC}),
            "allow": old.get("allow", []), "findings": [list(k) + [n] for k, n in sorted(cur.items())]}


def summary(sites):
    out = {}
    for s in sites:
        out.setdefault(s["cat"], {}).setdefault(s["group"], 0)
        out[s["cat"]][s["group"]] += 1
    return out
