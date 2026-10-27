import ast
import hashlib
import re

MODULE_Q = "<module>"
BODY_SUFFIX = ".<body>"
DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)

API_CALLS = {
    "urlopen": ("urllib.request.urlopen", "urllib.request.build_opener", "urllib.request.Request"),
    "hmac": ("hmac.new", "hmac.digest", "hmac.HMAC"),
    "sqlite": ("sqlite3.connect",),
    "replace": ("os.replace", "os.rename", "os.renames"),
}
API_OF = {name: kind for kind, names in API_CALLS.items() for name in names}
API_VALUE_KINDS = ("urlopen",)
API_VALUE_OF = {name: kind for name, kind in API_OF.items() if kind in API_VALUE_KINDS}
API_VALUE_LAST = frozenset(name.rsplit(".", 1)[-1] for name in API_VALUE_OF)
_CONV = ("float", "int", "Decimal")
_CONV_ERRORS = ("ValueError", "TypeError", "Exception", "BaseException", "InvalidOperation", "ArithmeticError",
                "OverflowError")
_STR_METHODS = ("strip", "lstrip", "rstrip", "replace", "lower", "upper")
HIST_WORDS = re.compile(r"코덱스|codex|핫픽스|hotfix|리팩터|라운드", re.IGNORECASE)
HIST_MARKS = re.compile(
    r"오너\s*\d"
    r"|(?<!\d)(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)"
    r"|\b20\d\d-\d\d-\d\d\b"
    r"|\b[A-Za-z]+(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[a-z]?\d?\b"
    r"|\d+차\b"
    r"|^\s*★?[A-Za-z][A-Za-z_-]*\d+[a-z]?\d*\s*[:(]"
    r"|\b[PSRWG]\d{1,2}[a-z]?\b")


_NOQA_HEAD = re.compile(r"^\s*#?\s*noqa\b(?::\s*[A-Z]+\d+\b(?:\s*,\s*[A-Z]+\d+\b)*)?")


def docstring_node(owner):
    body = getattr(owner, "body", None)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[0].value
    return None


def comment_norm(text):
    return " ".join(text.lstrip("#").split())


def is_history(text):
    text = _NOQA_HEAD.sub("", text)
    return bool(HIST_WORDS.search(text) or HIST_MARKS.search(text))


def counted_comment(body):
    if not re.search(r"\w", body):
        return False
    rest = re.sub(r"^noqa\b(:\s*[A-Z0-9, ]+)?", "", body).strip(" —-:·")
    return bool(re.search(r"\w", rest))


def depth(stmts, cur=0):
    best = cur
    for st in stmts:
        best = max(best, _depth_stmt(st, cur))
    return best


def _depth_stmt(st, cur):
    if isinstance(st, ast.If):
        best = depth(st.body, cur + 1)
        tail = st.orelse
        if len(tail) == 1 and isinstance(tail[0], ast.If) and tail[0].col_offset == st.col_offset:
            return max(best, _depth_stmt(tail[0], cur))
        return max(best, depth(tail, cur + 1))
    if isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
        return max(depth(st.body, cur + 1), depth(getattr(st, "orelse", []), cur + 1))
    if isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
        best = depth(st.body, cur + 1)
        for h in st.handlers:
            best = max(best, depth(h.body, cur + 1))
        return max(best, depth(st.orelse, cur + 1), depth(st.finalbody, cur + 1))
    if type(st).__name__ == "Match":
        return max([cur + 1] + [depth(c.body, cur + 1) for c in st.cases])
    return cur


def bs9_reloads(fn):
    n, stack = 0, list(fn.body)
    while stack:
        st = stack.pop()
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp, ast.SetComp,
                           ast.DictComp, ast.GeneratorExp)):
            continue
        if (isinstance(st, ast.If) and isinstance(st.test, ast.Compare) and len(st.test.ops) == 1 and isinstance(st.test.ops[0], ast.In)
                and isinstance(st.test.left, ast.Constant) and isinstance(st.test.left.value, str)
                and isinstance(st.test.comparators[0], ast.Name) and st.test.comparators[0].id == "_bs9"):
            n += 1
        stack.extend(ast.iter_child_nodes(st))
    return n


def arg_list_all(a):
    return list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs) + [x for x in (a.vararg, a.kwarg) if x is not None]


def arg_list(fn):
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if pos and pos[0].arg in ("self", "cls"):
        pos = pos[1:]
    return pos + list(a.kwonlyargs)


def _names_of(t):
    elts = t.elts if isinstance(t, ast.Tuple) else [t]
    return [getattr(x, "id", getattr(x, "attr", "?")) for x in elts]


def except_kind(h):
    if h.type is None:
        return "bare"
    return "broad" if any(n in ("Exception", "BaseException") for n in _names_of(h.type)) else "narrow"


def except_action(h):
    body = h.body
    has_raise = any(isinstance(y, ast.Raise) for st in body for y in ast.walk(st))
    rb = any(isinstance(y, ast.Attribute) and y.attr == "rollback" for st in body for y in ast.walk(st))
    if has_raise:
        return "rollback_reraise" if rb else "reraise"
    last = body[-1] if body else None
    logs = any(isinstance(y, ast.Call) and isinstance(y.func, ast.Attribute)
               and y.func.attr in ("debug", "info", "warning", "error", "exception")
               for st in body for y in ast.walk(st))
    if isinstance(last, ast.Return):
        return "return+log" if logs else "return"
    if isinstance(last, (ast.Continue, ast.Pass, ast.Break)) and len(body) == 1:
        return "swallow"
    return "log" if logs else "other"


def _is_swallowed(y):
    f = y.func if isinstance(y, ast.Call) else None
    return (isinstance(f, ast.Attribute) and f.attr == "swallowed" and isinstance(f.value, ast.Name)
            and f.value.id == "calcguard") or (isinstance(f, ast.Name) and f.id == "swallowed")


def calls_calcguard(h):
    return any(_is_swallowed(y) for st in h.body for y in ast.walk(st))


def swallow_pass(h):
    b = h.body
    return len(b) == 2 and isinstance(b[0], ast.Expr) and _is_swallowed(b[0].value) and isinstance(b[1], ast.Pass)


def _simple_of(e, p0):
    if isinstance(e, ast.Name):
        return e.id == p0
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "str" and len(e.args) == 1:
        return _simple_of(e.args[0], p0)
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr in _STR_METHODS:
        return _simple_of(e.func.value, p0)
    if isinstance(e, ast.BoolOp) and isinstance(e.op, ast.Or) and len(e.values) == 2 \
            and isinstance(e.values[1], ast.Constant):
        return _simple_of(e.values[0], p0)
    return False


def _conv_call(e, p0):
    if isinstance(e, ast.Call):
        return getattr(e.func, "id", getattr(e.func, "attr", None)) in _CONV and bool(e.args) \
            and _simple_of(e.args[0], p0)
    if isinstance(e, ast.IfExp):
        return _conv_call(e.body, p0) and _conv_call(e.orelse, p0)
    return False


def is_num_parser(fn):
    if fn.end_lineno - fn.lineno + 1 > 20:
        return False
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if pos and pos[0].arg in ("self", "cls"):
        pos = pos[1:]
    if not pos:
        return False
    p0 = pos[0].arg
    for tr in ast.walk(fn):
        if not isinstance(tr, ast.Try) or not tr.body:
            continue
        first = tr.body[0]
        val = first.value if isinstance(first, (ast.Assign, ast.Return, ast.AnnAssign)) else None
        if val is None or not _conv_call(val, p0):
            continue
        for h in tr.handlers:
            names = ["bare"] if h.type is None else _names_of(h.type)
            if any(n in _CONV_ERRORS or n == "bare" for n in names) and any(isinstance(x, ast.Return) for x in h.body):
                return True
    return False


_FP_SKIP_FIELDS = ("type_comment", "kind")


def _canon(node, memo):
    key = id(node)
    got = memo.get(key)
    if got is None:
        got = memo[key] = _hash_fields(node, memo, skip_name=False)
    return got


_FIELDS = {}


def _fields(t):
    got = _FIELDS.get(t)
    if got is None:
        got = _FIELDS[t] = tuple(x for x in t._fields if x not in _FP_SKIP_FIELDS)
    return got


def _hash_fields(node, memo, skip_name):
    parts = [type(node).__name__]
    for name in _fields(type(node)):
        if skip_name and name == "name":
            continue
        val = getattr(node, name, None)
        if val is None or (isinstance(val, list) and not val):
            continue
        if name == "body" and isinstance(node, DOC_OWNERS) and docstring_node(node) is not None:
            val = val[1:]
            if not val:
                continue
        if isinstance(val, list):
            parts.append(name + "=[" + ",".join(_canon(x, memo) if isinstance(x, ast.AST) else repr(x) for x in val) + "]")
        elif isinstance(val, ast.AST):
            parts.append(name + "=" + _canon(val, memo))
        else:
            parts.append(name + "=" + repr(val))
    return hashlib.blake2b("(".join(parts).encode("utf-8"), digest_size=8).hexdigest()


def fingerprint(node, memo):
    return _hash_fields(node, memo, skip_name=True)[:12]


def _top_statements(tree):
    out, todo = [], list(tree.body)
    while todo:
        st = todo.pop(0)
        out.append(st)
        if isinstance(st, (ast.If, ast.Try, ast.With)):
            todo[:0] = list(st.body) + list(getattr(st, "orelse", [])) + list(getattr(st, "finalbody", [])) \
                + [x for h in getattr(st, "handlers", []) for x in h.body]
    return out


def _bound_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for e in target.elts for n in _bound_names(e)]
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


def _modset_pairs(st):
    if not (isinstance(st, ast.Assign) and isinstance(st.value, ast.Tuple)
            and any(isinstance(t, ast.Name) and t.id in ("MODSET", "MODDICT") for t in st.targets)):
        return []
    return [[e.elts[0].value, e.elts[1].value] for e in st.value.elts
            if isinstance(e, ast.Tuple) and len(e.elts) >= 2
            and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in e.elts[:2])]


def module_facts(tree, resolve_from, used):
    defs, modset, from_bound = set(), [], {}
    for st in _top_statements(tree):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.add(st.name)
        elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                defs.update(_bound_names(t))
            modset.extend(_modset_pairs(st))
        elif isinstance(st, ast.Import):
            defs.update((a.asname or a.name.split(".")[0]) for a in st.names)
        elif isinstance(st, ast.ImportFrom):
            mod = resolve_from(st)
            for a in st.names:
                if a.name != "*":
                    defs.add(a.asname or a.name)
                    if mod != "__future__":
                        from_bound[a.asname or a.name] = (mod, a.name)
    used = set(used)
    for st in tree.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in st.targets):
            used.update(c.value for c in ast.walk(st.value) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    unused = sorted([mod, name, bound] for bound, (mod, name) in from_bound.items() if bound not in used)
    return sorted(defs), modset, unused, _reexport_only(tree)


def _reexport_only(tree):
    body = tree.body[1:] if docstring_node(tree) is not None else list(tree.body)
    has_import = False
    for st in body:
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            has_import = has_import or not (isinstance(st, ast.ImportFrom) and st.module == "__future__")
        elif isinstance(st, ast.Pass):
            continue
        elif isinstance(st, ast.Assign) and (isinstance(st.value, (ast.Name, ast.Attribute)) or any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in st.targets)):
            continue
        else:
            return False
    return has_import


_Q1, _Q2 = "'", '"'
_LEX = re.compile(
    "(?P<s>[rRbBuUfF]{0,2}(?:"
    + _Q1 * 3 + r"(?:\\[\s\S]|[^\\])*?" + _Q1 * 3 + "|"
    + _Q2 * 3 + r"(?:\\[\s\S]|[^\\])*?" + _Q2 * 3 + "|"
    + _Q1 + r"(?:\\.|[^'\\\n])*" + _Q1 + "|"
    + _Q2 + r'(?:\\.|[^"\\\n])*' + _Q2 + "))"
    + r"|(?P<c>#[^\n]*)")


def comment_facts(text, comment_at):
    total, hist = 0, []
    line, pos = 1, 0
    for m in _LEX.finditer(text):
        if m.lastgroup != "c":
            continue
        line += text.count("\n", pos, m.start())
        pos = m.start()
        raw = m.group("c").rstrip("\r")
        comment_at[line] = raw
        body = comment_norm(raw)
        if counted_comment(body):
            total += 1
            if is_history(body):
                hist.append(body)
    return total, hist


def bare_strings(tree):
    out, todo = [], [tree]
    while todo:
        node = todo.pop()
        for field in ("body", "orelse", "finalbody"):
            seq = getattr(node, field, None)
            if not isinstance(seq, list):
                continue
            for i, st in enumerate(seq):
                if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str) \
                        and not (field == "body" and i == 0 and isinstance(node, DOC_OWNERS)):
                    out.append(st.lineno)
        todo.extend(ast.iter_child_nodes(node))
    return sorted(set(out))


def doc_facts(doc_nodes):
    total, hist = 0, []
    for d in doc_nodes:
        for line in d.value.split("\n"):
            s = " ".join(line.split())
            if s:
                total += 1
                if is_history(s):
                    hist.append(s)
    return total, hist
