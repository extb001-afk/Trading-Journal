import ast
import re
import sys

import _arch_py_defs as D

_SKIP = (ast.expr_context, ast.operator, ast.boolop, ast.unaryop, ast.cmpop)
_NESTED_SCOPES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_TZ_CALLS = ("zoneinfo.ZoneInfo", "pytz.timezone", "dateutil.tz.gettz")
_WRITE_CALLS = ("os.open", "os.fdopen", "tempfile.mkstemp", "tempfile.NamedTemporaryFile")
_JOIN = ("os.path.join", "posixpath.join")
_SQL_WRITE = re.compile(
    r"\b(INSERT(?:\s+OR\s+(?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK))?\s+INTO|REPLACE\s+INTO|"
    r"UPDATE(?:\s+OR\s+(?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK))?|DELETE\s+FROM)"
    r"(?:\s+(?:(?:main|temp)\s*\.\s*)?[\"`\[]?([A-Za-z_]\w*)|\s*(\{[^}]*\}|%\(?\w*\)?s)|\s*$)", re.IGNORECASE)
_SQL_DDL = re.compile(r"\bCREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([A-Za-z_]\w*)", re.IGNORECASE)
_SQL_NOT_TABLE = ("SET", "OF")
_ENV_NAME = re.compile(r"TJ_[A-Z0-9_]*[A-Z0-9]")
_REASON = re.compile(r"noqa:\s*BLE001\s*\[([A-Za-z_-]+)\]")
_NOQA_BLE = re.compile(r"noqa:\s*[A-Z0-9, ]*BLE001")
PY310_TYPING = frozenset((
    "ParamSpec", "ParamSpecArgs", "ParamSpecKwargs", "Concatenate", "TypeAlias", "TypeGuard", "is_typeddict",
    "NotRequired", "Required", "Self", "LiteralString", "Never", "assert_never", "assert_type", "reveal_type",
    "dataclass_transform", "Unpack", "TypeVarTuple", "get_overloads", "clear_overloads", "override",
    "TypeAliasType", "get_protocol_members", "is_protocol", "ReadOnly", "TypeIs", "NoDefault"))
PY310_ATTRS = frozenset((
    ("itertools", "pairwise"), ("itertools", "batched"), ("datetime", "UTC"), ("enum", "StrEnum"),
    ("enum", "ReprEnum"), ("enum", "verify"), ("enum", "member"), ("enum", "nonmember"), ("enum", "global_enum"),
    ("enum", "EnumCheck"), ("enum", "FlagBoundary"), ("contextlib", "chdir"), ("contextlib", "aclosing"),
    ("hashlib", "file_digest"), ("asyncio", "TaskGroup"), ("asyncio", "timeout"), ("asyncio", "Runner"),
    ("math", "cbrt"), ("math", "exp2"), ("operator", "call"), ("inspect", "get_annotations"), ("sys", "orig_argv"),
    ("sys", "exception"), ("types", "NoneType"), ("types", "EllipsisType"), ("types", "NotImplementedType"),
    ("types", "UnionType"), ("dataclasses", "KW_ONLY"), ("logging", "getLevelNamesMapping"), ("re", "NOFLAG"),
    ("statistics", "correlation"), ("statistics", "covariance"), ("statistics", "linear_regression")))
PY310_MODULES = frozenset(("tomllib",))
PY310_BUILTINS = frozenset(("aiter", "anext", "ExceptionGroup", "BaseExceptionGroup", "EncodingWarning"))
PY310_KWARGS = {"zip": ("strict",), "dataclasses.dataclass": ("kw_only", "slots", "match_args", "weakref_slot"),
                "dataclasses.field": ("kw_only",), "bisect.bisect": ("key",), "bisect.bisect_left": ("key",),
                "bisect.bisect_right": ("key",), "bisect.insort": ("key",), "bisect.insort_left": ("key",),
                "bisect.insort_right": ("key",), "shutil.rmtree": ("onexc",)}
TYPE_NAMES = frozenset((
    "int", "float", "complex", "str", "bytes", "bytearray", "bool", "dict", "list", "tuple", "set", "frozenset",
    "type", "object", "memoryview", "range", "slice", "Any", "Optional", "Union", "List", "Dict", "Tuple", "Set",
    "FrozenSet", "Callable", "Iterable", "Iterator", "Sequence", "Mapping", "Generator", "Type", "Literal"))


def _state_dir_expr(e, aliases):
    if isinstance(e, ast.Name):
        return aliases.get(e.id, e.id).rsplit(".", 1)[-1] == "STATE_DIR"
    if isinstance(e, ast.Attribute):
        root = e.value
        while isinstance(root, ast.Attribute):
            root = root.value
        return e.attr == "STATE_DIR" and not (isinstance(root, ast.Name) and aliases.get(root.id) == "")
    if isinstance(e, ast.BoolOp):
        return any(_state_dir_expr(v, aliases) for v in e.values)
    if isinstance(e, ast.Call) and len(e.args) == 1 and isinstance(e.func, (ast.Name, ast.Attribute)):
        return getattr(e.func, "id", getattr(e.func, "attr", "")) in ("str", "fspath") and _state_dir_expr(e.args[0], aliases)
    return False


def _refs_cfg(e):
    if isinstance(e, ast.Name):
        return e.id == "cfg"
    for x in ast.walk(e):
        if (isinstance(x, ast.Name) and x.id == "cfg") or (isinstance(x, ast.Attribute) and x.attr == "cfg"):
            return True
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "getattr" and len(x.args) >= 2 \
                and isinstance(x.args[1], ast.Constant) and x.args[1].value == "cfg":
            return True
    return False


def _type_like(e):
    if isinstance(e, ast.Name):
        return e.id in TYPE_NAMES
    if isinstance(e, ast.Attribute):
        return e.attr in TYPE_NAMES
    if isinstance(e, ast.Subscript):
        return _type_like(e.value)
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.BitOr):
        return _type_like(e.left) or _type_like(e.right)
    return False


def _bump(sc, key, n=1):
    sc[key] = sc.get(key, 0) + n


def _shadow(aliases, names):
    names = set(names)
    if not names:
        return aliases
    out = dict(aliases)
    for x in names:
        out[x] = ""
    return out


class Walk:

    def __init__(self, text, modname, tree, is_pkg):
        self.mod, self.tree, self.memo = modname, tree, {}
        parts = modname.split(".")
        self.pkg = parts if is_pkg else parts[:-1]
        self.has_state = "STATE_DIR" in text
        self.future_ann = any(isinstance(s, ast.ImportFrom) and s.module == "__future__"
                              and any(a.name == "annotations" for a in s.names) for s in tree.body)
        self.units, self.scopes, self.skip = [], {}, set()
        self.env, self.ids9, self.n9, self.ddl = set(), set(), [0, 0], set()
        self.aliases, self.used, self.doc_nodes, self.comment_at = {}, set(), [], {}
        self.callee = set()
        self._prescan()
        self.docs = {id(d) for d in self.doc_nodes}
        self.on = {ast.Import: self.on_import, ast.ImportFrom: self.on_import, ast.Call: self.on_call,
                   ast.Subscript: self.on_subscript, ast.Constant: self.on_const, ast.JoinedStr: self.on_fstring,
                   ast.BinOp: self.on_binop, ast.Attribute: self.on_attr, ast.Name: self.on_name,
                   ast.ExceptHandler: self.on_except, ast.keyword: self.on_keyword,
                   ast.alias: self.on_alias, ast.arg: self.on_arg}
        for nm, label in (("Match", "match"), ("TryStar", "except*"), ("TypeAlias", "type 별칭(3.12+)")):
            if hasattr(ast, nm):
                self.on[getattr(ast, nm)] = lambda n, sc, f, a, lb=label: sc.setdefault("py310", []).append(lb)

    def resolve_from(self, node):
        if not node.level:
            return node.module or ""
        base = self.pkg[:len(self.pkg) - (node.level - 1)] if node.level > 1 else list(self.pkg)
        return ".".join(base + ([node.module] if node.module else []))

    def _prescan(self):
        for n in ast.walk(self.tree):
            t = type(n)
            if t is ast.Name:
                self.used.add(n.id)
            elif t in D.DOC_OWNERS:
                d = D.docstring_node(n)
                if d is not None:
                    self.doc_nodes.append(d)
        self.aliases = self.local_imports(self.tree.body)
        self.lexical = self.module_aliases = self.aliases

    def local_imports(self, stmts, globals_out=None):
        out, todo = {}, list(stmts)
        while todo:
            n = todo.pop(0)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(n, ast.Import):
                for a in n.names:
                    top = a.name.split(".")[0]
                    out[a.asname or top] = a.name if a.asname else top
            elif isinstance(n, ast.ImportFrom):
                mod = self.resolve_from(n)
                for a in n.names:
                    if a.name != "*":
                        out[a.asname or a.name] = (mod + "." + a.name) if mod else a.name
            elif isinstance(n, ast.Global) and globals_out is not None:
                globals_out.update(n.names)
            todo.extend(ast.iter_child_nodes(n))
        return out

    def body(self, stmts, q, inner, qual, fpath, in_func, is_class=False, params=()):
        outer, outer_lex = self.aliases, self.lexical
        glob = set()
        local = self.local_imports(stmts, glob)
        aliases = dict(_shadow(outer_lex, params))
        for name in glob:
            aliases.pop(name, None)
            if name in self.module_aliases:
                aliases[name] = self.module_aliases[name]
        self.aliases = dict(aliases, **local)
        if not is_class:
            self.lexical = self.aliases
        try:
            for st in stmts:
                self.node(st, q, inner, qual, fpath, in_func, None)
        finally:
            self.aliases, self.lexical = outer, outer_lex

    def state_valued(self, e):
        if isinstance(e, ast.Call):
            nm = self.dotted(e.func)
            return nm == "paths.state" or (nm in _JOIN and bool(e.args) and self.state_valued(e.args[0]))
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
            return self.state_valued(e.left)
        if isinstance(e, ast.IfExp):
            return self.state_valued(e.body) or self.state_valued(e.orelse)
        if isinstance(e, ast.BoolOp):
            return any(self.state_valued(v) for v in e.values)
        return False

    def dotted(self, e):
        attrs = []
        while isinstance(e, ast.Attribute):
            attrs.append(e.attr)
            e = e.value
        if not isinstance(e, ast.Name):
            return ""
        return ".".join([self.aliases.get(e.id, e.id)] + attrs[::-1])

    def name9(self, name, decl, sc):
        if name and name[-1] == "9":
            self.n9[0 if decl else 1] += 1
            self.ids9.add(name)
            if decl:
                b9 = sc.setdefault("b9", [])
                if name not in b9:
                    b9.append(name)

    def run(self):
        sc = self.scopes.setdefault(D.MODULE_Q, {})
        for st in self.tree.body:
            self.node(st, D.MODULE_Q, sc, [], [], False, None)

    def node(self, n, sq, sc, qual, fpath, in_func, ann):
        t = type(n)
        if (t in D.FUNCS or t is ast.ClassDef) and getattr(n, "type_params", None):
            sc.setdefault("py310", []).append("타입 매개변수(3.12+)")
        if t in D.FUNCS:
            return self.func(n, sq, sc, qual, fpath, in_func)
        if t is ast.ClassDef:
            return self.klass(n, sq, sc, qual, fpath, in_func)
        if t is ast.Return:
            before = sc.get("sp", 0)
            if n.value is not None:
                self.node(n.value, sq, sc, qual, fpath, in_func, ann)
            if sc.get("sp", 0) > before or (n.value is not None and self.state_valued(n.value)):
                _bump(sc, "spret")
            return None
        h = self.on.get(t)
        if h is not None:
            h(n, sc, in_func, ann)
        if t in _NESTED_SCOPES:
            return self.nested_expr(n, sq, sc, qual, fpath, in_func, ann)
        if t is ast.AnnAssign:
            evaluated = (sq == D.MODULE_Q or sq.endswith(D.BODY_SUFFIX)) and not self.future_ann
            self.node(n.target, sq, sc, qual, fpath, in_func, None)
            self.node(n.annotation, sq, sc, qual, fpath, in_func, "eval" if evaluated else "lazy")
            if n.value is not None:
                self.node(n.value, sq, sc, qual, fpath, in_func, None)
            return None
        for name in n._fields:
            v = getattr(n, name, None)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, ast.AST) and not isinstance(x, _SKIP):
                        self.node(x, sq, sc, qual, fpath, in_func, ann)
            elif isinstance(v, ast.AST) and not isinstance(v, _SKIP):
                self.node(v, sq, sc, qual, fpath, in_func, ann)
        return None

    def nested_expr(self, n, sq, sc, qual, fpath, in_func, ann):
        if isinstance(n, ast.Lambda):
            outer_part, inner_part = [n.args], [n.body]
            bound = [x.arg for x in D.arg_list_all(n.args)]
        else:
            first = n.generators[0]
            outer_part = [first.iter]
            inner_part = [first.target] + list(first.ifs) + [x for g in n.generators[1:] for x in (g.target, g.iter, *g.ifs)] \
                + [getattr(n, f) for f in ("elt", "key", "value") if getattr(n, f, None) is not None]
            bound = [name for g in n.generators for name in D._bound_names(g.target)]
        for x in outer_part:
            self.node(x, sq, sc, qual, fpath, in_func, ann)
        saved, saved_lex = self.aliases, self.lexical
        self.aliases = self.lexical = _shadow(self.lexical, bound)
        try:
            for x in inner_part:
                self.node(x, sq, sc, qual, fpath, in_func, ann)
        finally:
            self.aliases, self.lexical = saved, saved_lex
        return None

    def func(self, fn, sq, sc, qual, fpath, in_func):
        q, fp = ".".join(qual + [fn.name]), ".".join(fpath + [fn.name])
        a, args = fn.args, D.arg_list(fn)
        self.units.append({
            "q": q, "t": "f", "f": fp, "l0": fn.lineno, "l1": fn.end_lineno, "h": D.fingerprint(fn, self.memo),
            "len": fn.end_lineno - fn.lineno + 1, "args": len(args) + bool(a.vararg) + bool(a.kwarg),
            "depth": D.depth(fn.body), "na": len(args), "unt": sum(1 for x in args if x.annotation is None),
            "pub": not in_func and not fn.name.startswith("_") and not any(p.startswith("_") for p in qual),
            "doc": bool((ast.get_docstring(fn) or "").strip()), "reload": D.bs9_reloads(fn)})
        self.name9(fn.name, True, sc)
        inner = self.scopes.setdefault(q, {})
        for d in fn.decorator_list + a.defaults + [x for x in a.kw_defaults if x is not None]:
            self.node(d, sq, sc, qual, fpath, in_func, None)
        mode = "lazy" if self.future_ann else "eval"
        for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x is not None]:
            self.name9(arg.arg, True, inner)
            if arg.annotation is not None:
                self.node(arg.annotation, sq, sc, qual, fpath, in_func, mode)
        if fn.returns is not None:
            self.node(fn.returns, sq, sc, qual, fpath, in_func, mode)
        if D.is_num_parser(fn):
            inner["num"] = 1
        self.body(fn.body, q, inner, qual + [fn.name], fpath + [fn.name], True, params=[x.arg for x in D.arg_list_all(a)])
        if inner.get("api.replace") and inner.get("wopen"):
            inner["atomic"] = 1

    def klass(self, c, sq, sc, qual, fpath, in_func):
        q = ".".join(qual + [c.name])
        bases = [getattr(b, "id", getattr(b, "attr", "")) for b in c.bases]
        decos = [self.dotted(d.func if isinstance(d, ast.Call) else d) for d in c.decorator_list]
        contract = "dataclass" if any(d in ("dataclasses.dataclass", "dataclass") for d in decos) else \
            next((b for b in bases if b in ("TypedDict", "NamedTuple")), "")
        self.units.append({
            "q": q, "t": "c", "l0": c.lineno, "l1": c.end_lineno, "h": D.fingerprint(c, self.memo),
            "len": c.end_lineno - c.lineno + 1, "meth": sum(1 for s in c.body if isinstance(s, D.FUNCS)),
            "mixb": sum(1 for b in bases if b.endswith("Mixin")), "mixin": c.name.endswith("Mixin"),
            "contract": contract})
        self.name9(c.name, True, sc)
        for d in c.decorator_list + c.bases + [k.value for k in c.keywords]:
            self.node(d, sq, sc, qual, fpath, in_func, None)
        body_q = q + D.BODY_SUFFIX
        inner = self.scopes.setdefault(body_q, {})
        self.body(c.body, body_q, inner, qual + [c.name], fpath, in_func, is_class=True)

    def api_value(self, n, last, sc):
        if last in D.API_VALUE_LAST and id(n) not in self.callee and isinstance(n.ctx, ast.Load):
            api = D.API_VALUE_OF.get(self.dotted(n))
            if api:
                _bump(sc, "api." + api)

    def on_name(self, n, sc, in_func, ann):
        self.name9(n.id, not isinstance(n.ctx, ast.Load), sc)
        self.api_value(n, (self.aliases.get(n.id) or "").rsplit(".", 1)[-1], sc)
        if n.id in PY310_BUILTINS and isinstance(n.ctx, ast.Load) and self.aliases.get(n.id) != "":
            sc.setdefault("py310", []).append(n.id)

    def on_keyword(self, n, sc, in_func, ann):
        self.name9(n.arg, False, sc)

    def on_arg(self, n, sc, in_func, ann):
        self.name9(n.arg, True, sc)

    def on_alias(self, n, sc, in_func, ann):
        self.name9((n.asname or n.name).split(".")[0], True, sc)

    def on_import(self, n, sc, in_func, ann):
        if isinstance(n, ast.Import):
            for a in n.names:
                sc.setdefault("imp", []).append([n.lineno, int(in_func), "import", a.name, []])
                if a.name.split(".")[0] in PY310_MODULES:
                    sc.setdefault("py310", []).append(a.name)
            return
        mod = self.resolve_from(n)
        names = [a.name for a in n.names]
        sc.setdefault("imp", []).append([n.lineno, int(in_func), "from", mod, names])
        if "*" in names:
            _bump(sc, "star")
        for nm in names:
            if (mod == "typing" and nm in PY310_TYPING) or (mod, nm) in PY310_ATTRS or mod in PY310_MODULES:
                sc.setdefault("py310", []).append(mod + "." + nm)
            if nm.startswith("_") and not nm.startswith("__"):
                sc.setdefault("priv", []).append([mod, nm])

    def on_call(self, n, sc, in_func, ann):
        name = self.dotted(n.func)
        api = D.API_OF.get(name)
        if api:
            _bump(sc, "api." + api)
            self.callee.add(id(n.func))
        if name == "datetime.timedelta" and any(k.arg == "hours" and isinstance(k.value, ast.Constant)
                                                and k.value.value == 9 for k in n.keywords):
            _bump(sc, "kst")
        elif name in _TZ_CALLS and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "Asia/Seoul":
            _bump(sc, "kst")
        if isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and _refs_cfg(n.func.value):
            _bump(sc, "cfg")
        if self.has_state and name in _JOIN and n.args and _state_dir_expr(n.args[0], self.aliases):
            _bump(sc, "sp")
        if self.write_open(n, name):
            _bump(sc, "wopen")
        kw = PY310_KWARGS.get(name)
        if kw and any(k.arg in kw for k in n.keywords):
            sc.setdefault("py310", []).append(name + "(" + ",".join(k.arg for k in n.keywords if k.arg in kw) + "=)")
        if name in ("isinstance", "issubclass") and len(n.args) == 2 \
                and any(isinstance(x, ast.BinOp) and isinstance(x.op, ast.BitOr) for x in ast.walk(n.args[1])):
            sc.setdefault("py310", []).append(name + "(X | Y)")
        if name in ("__import__", "importlib.import_module") and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            sc.setdefault("imp", []).append([n.lineno, int(in_func), "import", n.args[0].value, []])

    @staticmethod
    def write_open(n, name):
        if name in _WRITE_CALLS:
            return True
        if isinstance(n.func, ast.Attribute) and n.func.attr in ("write_text", "write_bytes"):
            return True
        if name in ("open", "io.open", "builtins.open"):
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
            return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+")
        return False

    def state_site(self, x):
        if isinstance(x, ast.Call):
            return self.dotted(x.func) in _JOIN and bool(x.args) and _state_dir_expr(x.args[0], self.aliases)
        if isinstance(x, ast.BinOp) and isinstance(x.op, (ast.Add, ast.Div)):
            left = x.left
            if isinstance(left, ast.Call) and self.dotted(left.func) in ("pathlib.Path", "Path") and left.args:
                left = left.args[0]
            return _state_dir_expr(left, self.aliases)
        if isinstance(x, ast.JoinedStr):
            return any(isinstance(v, ast.FormattedValue) and _state_dir_expr(v.value, self.aliases) for v in x.values)
        return False

    def on_subscript(self, n, sc, in_func, ann):
        if isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str) and _refs_cfg(n.value):
            _bump(sc, "cfg")

    def on_const(self, n, sc, in_func, ann):
        v = n.value
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            if v == 1384:
                _bump(sc, "c1384")
            elif v == 32400:
                _bump(sc, "kst")
            return
        if not isinstance(v, str) or id(n) in self.docs or id(n) in self.skip:
            return
        if v.startswith("TJ_") and _ENV_NAME.fullmatch(v) and not v.startswith("TJ_TEST_"):
            self.env.add(v)
        self.sql(v, sc)

    def on_fstring(self, n, sc, in_func, ann):
        parts = []
        for v in n.values:
            if isinstance(v, ast.Constant):
                self.skip.add(id(v))
                parts.append(str(v.value))
            else:
                parts.append("{}")
        self.sql("".join(parts), sc)
        if self.has_state and self.state_site(n):
            _bump(sc, "sp")

    def sql(self, s, sc):
        up = s.upper()
        if "CREATE" in up:
            self.ddl.update(t.lower() for t in _SQL_DDL.findall(s))
        if "INSERT" not in up and "UPDATE" not in up and "DELETE" not in up and "REPLACE" not in up:
            return
        for m in _SQL_WRITE.finditer(s):
            word = m.group(1).split()[0].upper()
            table = m.group(2)
            if table and table.upper() in _SQL_NOT_TABLE:
                continue
            key = (table.lower() if table else "{dyn}") + ":" + word
            led = sc.setdefault("led", [])
            if key not in led:
                led.append(key)

    def on_binop(self, n, sc, in_func, ann):
        if isinstance(n.op, ast.Mult) and isinstance(n.left, ast.Constant) and isinstance(n.right, ast.Constant) \
                and {n.left.value, n.right.value} == {9, 3600}:
            _bump(sc, "kst")
        if self.has_state and isinstance(n.op, (ast.Add, ast.Div)) and self.state_site(n):
            _bump(sc, "sp")
        if not isinstance(n.op, ast.BitOr) or id(n) in self.skip:
            return
        for side in (n.left, n.right):
            if isinstance(side, ast.BinOp) and isinstance(side.op, ast.BitOr):
                self.skip.add(id(side))
        if ann == "eval":
            sc.setdefault("py310", []).append("X | Y(평가되는 주석)")
        elif ann is None and (_type_like(n.left) or _type_like(n.right)):
            sc.setdefault("py310", []).append("X | Y(실행 중 타입식)")

    def on_attr(self, n, sc, in_func, ann):
        self.name9(n.attr, isinstance(n.ctx, ast.Store), sc)
        self.api_value(n, n.attr, sc)
        if not isinstance(n.value, ast.Name):
            return
        target = self.aliases.get(n.value.id)
        if not target:
            return
        if n.attr.startswith("_") and not n.attr.startswith("__"):
            sc.setdefault("priv", []).append([target, n.attr])
        if (target == "typing" and n.attr in PY310_TYPING) or (target, n.attr) in PY310_ATTRS:
            sc.setdefault("py310", []).append(target + "." + n.attr)

    def on_except(self, h, sc, in_func, ann):
        self.name9(h.name, True, sc)
        note = self.comment_at.get(h.lineno, "")
        code = _REASON.search(note)
        last_raise = bool(h.body) and isinstance(h.body[-1], ast.Raise)
        sc.setdefault("exc", []).append([D.except_kind(h), int(last_raise), int(D.calls_calcguard(h)),
                                         code.group(1).lower() if code else "", int(bool(_NOQA_BLE.search(note)))])


def facts(text, modname, is_pkg=False):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return {"error": "구문 오류 %s:%s %s" % (modname, e.lineno, e.msg)}
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 20000))
    try:
        walk = Walk(text, modname, tree, is_pkg)
        n_doc, doc_hist = D.doc_facts(walk.doc_nodes)
        n_comments, hist = D.comment_facts(text, walk.comment_at)
        walk.run()
    finally:
        sys.setrecursionlimit(old)
    defs, modset, unused, reexport = D.module_facts(tree, walk.resolve_from, walk.used)
    return {
        "lines": len(text.splitlines()), "bytes": len(text.encode("utf-8")),
        "units": walk.units, "scopes": {q: sc for q, sc in walk.scopes.items() if sc},
        "env": sorted(walk.env), "ddl": sorted(walk.ddl), "defs": defs, "modset": modset, "unused_from": unused,
        "reexport_only": reexport,
        "n9": walk.n9, "ids9": sorted(walk.ids9),
        "comments": [n_comments, len(hist)], "hist": sorted(set(hist)),
        "doclines": [n_doc, len(doc_hist)], "dochist": sorted(set(doc_hist)),
    }
