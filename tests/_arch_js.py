from __future__ import annotations

import io
import os
import re
import tokenize as _pytok
from typing import NamedTuple

LIMITS = {
    "file_lines": 600,
    "file_bytes": 48_000,
    "file_hard_lines": 800,
    "fn_lines": 80,
    "fn_target": 60,
    "line_chars": 140,
}


class Tok(NamedTuple):
    kind: str
    val: str
    line: int


class JSError(ValueError):

    def __init__(self, line: int, why: str):
        super().__init__(f"{line}번 줄: {why}")
        self.line, self.why = line, why


_SP = re.compile(r"[ \t\r\f\v\u00a0\ufeff\u2028\u2029]+")
_ID = re.compile(r"[#A-Za-z_$\u0080-\uffff][A-Za-z0-9_$\u0080-\uffff]*")
_NUM = re.compile(r"0[xX][0-9a-fA-F_]+n?|0[oO][0-7_]+n?|0[bB][01_]+n?"
                  r"|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?")
_STR = {q: re.compile(q + r"(?:[^" + q + r"\\\n]|\\(?:\r\n|[\s\S]))*" + q) for q in ("'", '"')}
_TPL = re.compile(r"(?:[^`\\$]|\\[\s\S]|\$(?!\{))*")
_RE = re.compile(r"/(?![*/])(?:[^/\\\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[A-Za-z]*")
_OP = re.compile(r">>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|&&=|\|\|=|\?\?=|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.(?!\d)"
                 r"|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\*\*|<<|>>")
_KW_EXPR = frozenset("return typeof instanceof in of new delete void throw case do else yield await".split())


def _regex_ok(prev: Tok | None) -> bool:
    if prev is None:
        return True
    if prev.kind == "p":
        return prev.val not in (")", "]", "++", "--")
    if prev.kind == "id":
        return prev.val in _KW_EXPR
    return False


class _Scanner:

    def __init__(self, text: str):
        self.text, self.n = text, len(text)
        self.i = (text.find("\n") if "\n" in text else self.n) if text.startswith("#!") else 0
        self.line, self.depth = 1, 0
        self.tpl: list[int] = []
        self.prev: Tok | None = None
        self.toks: list[Tok] = []

    def push(self, kind: str, val: str, end: int, nl: int = 0) -> None:
        self.prev = Tok(kind, val, self.line)
        self.toks.append(self.prev)
        self.line += nl
        self.i = end

    def skip(self) -> bool:
        t, i = self.text, self.i
        if t[i] == "\n":
            self.line, self.i = self.line + 1, i + 1
            return True
        m = _SP.match(t, i)
        if m:
            self.i = m.end()
            return True
        if t.startswith("//", i):
            j = t.find("\n", i)
            self.i = self.n if j < 0 else j
            return True
        if t.startswith("/*", i):
            j = t.find("*/", i + 2)
            if j < 0:
                raise JSError(self.line, "끝나지 않은 /* 주석")
            self.line, self.i = self.line + t.count("\n", i, j), j + 2
            return True
        return False

    def string(self, q: str) -> None:
        m = _STR[q].match(self.text, self.i)
        if not m:
            raise JSError(self.line, "끝나지 않은 문자열")
        self.push("str", self.text[self.i + 1:m.end() - 1], m.end(), self.text.count("\n", self.i, m.end()))

    def template(self, closing_expr: bool) -> None:
        if closing_expr:
            self.tpl.pop()
        i = self.i
        j = _TPL.match(self.text, i + 1).end()
        if j >= self.n:
            raise JSError(self.line, "끝나지 않은 템플릿 리터럴")
        opened = self.text[j] == "$"
        end = j + (2 if opened else 1)
        self.push("tpl", self.text[i:end], end, self.text.count("\n", i, end))
        if opened:
            self.tpl.append(self.depth)
            self.prev = Tok("p", "${", self.line)

    def regex(self) -> bool:
        m = _RE.match(self.text, self.i)
        if m:
            self.push("re", m.group(), m.end())
        return bool(m)

    def other(self, c: str) -> None:
        t, i = self.text, self.i
        if "0" <= c <= "9" or (c == "." and i + 1 < self.n and "0" <= t[i + 1] <= "9"):
            m = _NUM.match(t, i)
            return self.push("num", m.group(), m.end())
        m = _ID.match(t, i)
        if m:
            return self.push("id", m.group(), m.end())
        m = _OP.match(t, i)
        if m:
            return self.push("p", m.group(), m.end())
        self.depth += {"{": 1, "}": -1}.get(c, 0)
        self.push("p", c, i + 1)

    def run(self) -> list[Tok]:
        while self.i < self.n:
            if self.skip():
                continue
            c = self.text[self.i]
            if c in "'\"":
                self.string(c)
            elif c == "`" or (c == "}" and self.tpl and self.tpl[-1] == self.depth):
                self.template(c == "}")
            elif not (c == "/" and _regex_ok(self.prev) and self.regex()):
                self.other(c)
        if self.tpl:
            raise JSError(self.line, "닫히지 않은 템플릿 `${`")
        return self.toks


def tokenize(text: str) -> list[Tok]:
    return _Scanner(text).run()


_PAIR = {"(": ")", "[": "]", "{": "}"}
_CONTROL = frozenset("if for while switch catch with function return typeof new await yield do else in of".split())
_METHOD_PRE = frozenset(["{", ",", "}", ";", "*"])
_MODS = frozenset(["static", "async", "get", "set"])


def _lhs_name(toks: list[Tok], j: int) -> str:
    parts = []
    while j >= 0 and toks[j].kind == "id":
        parts.append(toks[j].val)
        if j >= 1 and toks[j - 1].kind == "p" and toks[j - 1].val in (".", "?."):
            j -= 2
            continue
        break
    if not parts:
        return "<computed>" if j >= 0 and toks[j].val == "]" else "<anon>"
    return ".".join(reversed(parts))


def _callee_name(toks: list[Tok], stack: list[tuple[str, int, int]]) -> str:
    if not stack:
        return "<anon>"
    o, k, _ = stack[-1]
    if o == "[":
        return "<array>"
    if o != "(":
        return "<anon>"
    b = toks[k - 1] if k >= 1 else None
    if b is not None and b.kind == "id" and b.val not in _CONTROL:
        return b.val + "()"
    if b is not None and b.kind == "p" and b.val in (")", "]"):
        return "<call>()"
    return "<iife>"


def _ctx_name(toks: list[Tok], s: int, stack: list[tuple[str, int, int]]) -> str:
    if s == 0:
        return "<anon>"
    b = toks[s - 1]
    if b.kind == "p":
        if b.val in ("=", "||=", "&&=", "??="):
            return _lhs_name(toks, s - 2)
        if b.val == ":":
            a, c = (toks[s - 2] if s >= 2 else None), (toks[s - 3] if s >= 3 else None)
            if a is not None and a.kind in ("id", "str", "num") and c is not None and c.kind == "p" and c.val in ("{", ","):
                return a.val
            return "<cond>"
        if b.val in ("(", ","):
            return _callee_name(toks, stack)
        if b.val == "?":
            return "<cond>"
        if b.val == "=>":
            return "<arrow>"
    if b.kind == "id" and b.val == "return":
        return "<return>"
    return "<anon>"


def _fn_head(toks: list[Tok], k: int, match: dict[int, int], stack: list[tuple[str, int, int]]):
    if k == 0:
        return None
    p = toks[k - 1]
    if p.kind == "p" and p.val == "=>":
        q = k - 2
        if q < 0:
            return None
        if toks[q].kind == "p" and toks[q].val == ")":
            s = match.get(q)
        elif toks[q].kind == "id":
            s = q
        else:
            return None
        if s is None:
            return None
        if s >= 1 and toks[s - 1].kind == "id" and toks[s - 1].val == "async":
            s -= 1
        return _ctx_name(toks, s, stack), s, "arrow"
    if not (p.kind == "p" and p.val == ")"):
        return None
    o = match.get(k - 1)
    if not o:
        return None
    b = toks[o - 1]
    s = None
    if b.kind == "id" and b.val == "function":
        s, name = o - 1, None
    elif b.kind == "p" and b.val == "*" and o >= 2 and toks[o - 2].val == "function":
        s, name = o - 2, None
    elif b.kind in ("id", "str", "num"):
        a = toks[o - 2] if o >= 2 else None
        if a is not None and a.kind == "id" and a.val == "function":
            s, name = o - 2, b.val
        elif a is not None and a.val == "*" and o >= 3 and toks[o - 3].val == "function":
            s, name = o - 3, b.val
        elif b.kind == "id" and b.val in _CONTROL:
            return None
        elif a is None or (a.kind == "p" and a.val in _METHOD_PRE) or (a.kind == "id" and a.val in _MODS):
            s = o - 1
            while s >= 1 and (toks[s - 1].kind == "id" and toks[s - 1].val in _MODS or toks[s - 1].val == "*"):
                s -= 1
            return b.val, s, "method"
    if s is None:
        return None
    if s >= 1 and toks[s - 1].kind == "id" and toks[s - 1].val == "async":
        s -= 1
    return (name if name is not None else _ctx_name(toks, s, stack)), s, ("decl" if _stmt_start(toks, s) else "expr")


def _stmt_start(toks: list[Tok], s: int) -> bool:
    if s == 0:
        return True
    b = toks[s - 1]
    if b.kind == "p" and b.val in (";", "{", "}"):
        return True
    ends = b.kind in ("num", "str", "tpl", "re") or (b.kind == "id" and b.val not in _KW_EXPR) or \
        (b.kind == "p" and b.val in (")", "]", "++", "--"))
    return ends and b.line < toks[s].line


_UNARY_IIFE = frozenset(["!", "+", "-", "~", "void"])
_STMT_EDGE = frozenset([";", "{", "}"])


def _assign_stmt(toks: list[Tok], eq: int, match: dict[int, int]) -> bool:
    j = eq - 1
    start = eq
    while j >= 0:
        t = toks[j]
        if t.kind == "id":
            start = j
        elif t.kind == "p" and t.val in (")", "]") and j in match:
            start = match[j]
        else:
            return False
        j = start - 1
        if j >= 0 and toks[j].kind == "p" and toks[j].val in (".", "?."):
            j -= 1
            continue
        if t.kind == "p" and t.val == "]" and j >= 0 and (toks[j].kind == "id" or toks[j].val in (")", "]")):
            continue
        break
    if start >= 1 and toks[start - 1].kind == "id" and toks[start - 1].val in ("const", "let", "var"):
        start -= 1
    if start >= 1 and toks[start - 1].kind == "p" and toks[start - 1].val == "=":
        return _assign_stmt(toks, start - 1, match)
    return _stmt_start(toks, start)


def _wrapper_slot(toks: list[Tok], s: int, stack: list[tuple[str, int, int]], match: dict[int, int]) -> bool:
    opened = sum(1 for e in stack if e[1] < s)
    b = toks[s - 1] if s >= 1 else None
    if b is None:
        return False
    grouped = b.kind == "p" and b.val == "("
    if opened != (1 if grouped else 0):
        return False
    p = s - (2 if grouped else 1)
    if p < 0:
        return grouped
    if toks[p].kind == "p" and toks[p].val == "=":
        return _assign_stmt(toks, p, match)
    if toks[p].val in _UNARY_IIFE:
        return grouped or _stmt_start(toks, p)
    return grouped and toks[p].kind == "p" and toks[p].val in _STMT_EDGE


def find_functions(toks: list[Tok]) -> list[dict]:
    fns: list[dict] = []
    stack: list[tuple[str, int, int]] = []
    match: dict[int, int] = {}
    for k, t in enumerate(toks):
        if t.kind != "p":
            continue
        v = t.val
        if v in _PAIR:
            fi = -1
            if v == "{":
                head = _fn_head(toks, k, match, stack)
                if head is not None:
                    s = head[1]
                    fns.append({"name": head[0], "start": toks[s].line, "end": None, "parent": -1, "kind": head[2],
                                "s_tok": s, "e_tok": None, "top_slot": _wrapper_slot(toks, s, stack, match)})
                    fi = len(fns) - 1
            stack.append((v, k, fi))
        elif v in (")", "]", "}"):
            if not stack or _PAIR[stack[-1][0]] != v:
                raise JSError(t.line, f"닫는 '{v}' 의 짝이 없음")
            _o, ok, fi = stack.pop()
            if v in (")", "]"):
                match[k] = ok
            if fi >= 0:
                fns[fi]["end"], fns[fi]["e_tok"] = t.line, k
    if stack:
        raise JSError(toks[stack[-1][1]].line, f"열린 '{stack[-1][0]}' 가 닫히지 않음")
    _parents(fns)
    return fns


def _parents(fns: list[dict]) -> None:
    stack: list[int] = []
    for i in sorted(range(len(fns)), key=lambda j: (fns[j]["s_tok"], -fns[j]["e_tok"])):
        while stack and fns[stack[-1]]["e_tok"] < fns[i]["s_tok"]:
            stack.pop()
        fns[i]["parent"] = stack[-1] if stack else -1
        stack.append(i)


def qualify(fns: list[dict], nlines: int) -> None:
    for f in fns:
        f["lines"] = f["end"] - f["start"] + 1
        f["wrapper"] = (f["parent"] < 0 and f["kind"] in ("expr", "arrow") and f["lines"] * 2 >= nlines
                        and f.get("top_slot", False))
    for f in fns:
        parts, g = [], f
        while True:
            if not g["wrapper"]:
                parts.append(g["name"])
            if g["parent"] < 0:
                break
            g = fns[g["parent"]]
        f["qual"] = ">".join(reversed(parts)) or "<wrapper>"


_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_NOT_JS = re.compile(r"json|template|html|importmap|markdown|plain|css|speculationrules", re.I)


class Unit(NamedTuple):
    path: str
    offset: int
    text: str


def _rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace(os.sep, "/")


def web_files(root: str) -> list[str]:
    out = []
    for dp, dn, fns in os.walk(os.path.join(root, "web")):
        dn[:] = sorted(d for d in dn if d != "fonts")
        out += [os.path.join(dp, f) for f in fns if f.endswith((".js", ".html"))]
    return sorted(out, key=lambda p: _rel(root, p))


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as f:
        return f.read()


def html_scripts(text: str) -> list[tuple[int, str]]:
    out = []
    for m in _SCRIPT.finditer(text):
        attrs = m.group(1)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        ty = re.search(r"""\btype\s*=\s*["']?([^"'\s>]+)""", attrs, re.I)
        if ty and _NOT_JS.search(ty.group(1)):
            continue
        out.append((text.count("\n", 0, m.start(2)), m.group(2)))
    return out


def js_units(root: str) -> list[Unit]:
    units = []
    for p in web_files(root):
        rel, text = _rel(root, p), _read(p)
        if p.endswith(".js"):
            units.append(Unit(rel, 0, text))
        else:
            units += [Unit(rel, off, js) for off, js in html_scripts(text)]
    return units


def nlines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _num_val(s: str) -> float | None:
    s = s.replace("_", "").rstrip("n")
    try:
        return float(int(s, 0)) if s[:2].lower() in ("0x", "0o", "0b") else float(s)
    except ValueError:
        return None


def _tpl_plain(val: str) -> str | None:
    return val[1:-1] if len(val) >= 2 and val[0] == "`" and val[-1] == "`" else None


def unit_metrics(u: Unit) -> dict:
    long_n = sum(1 for ln in u.text.split("\n") if len(ln.rstrip("\r")) > LIMITS["line_chars"])
    try:
        toks = tokenize(u.text)
        fns = find_functions(toks)
    except JSError as e:
        return {"fns": [], "long": long_n, "esc": 0, "n1384": 0, "error": (e.line + u.offset, e.why)}
    qualify(fns, nlines(u.text))
    for f in fns:
        f["start"] += u.offset
        f["end"] += u.offset
        f["file"] = u.path
    esc = sum(1 for t in toks if (t.kind == "str" and t.val == "&amp;") or (t.kind == "tpl" and _tpl_plain(t.val) == "&amp;"))
    n1384 = sum(1 for t in toks if t.kind == "num" and _num_val(t.val) == 1384)
    return {"fns": fns, "long": long_n, "esc": esc, "n1384": n1384, "error": None}


def metrics(root: str) -> dict:
    out = {"size": {}, "fns": [], "long": {}, "esc": {}, "n1384": {}, "errors": [], "units": 0}
    for p in web_files(root):
        rel = _rel(root, p)
        with open(p, "rb") as f:
            raw = f.read()
        out["size"][rel] = {"lines": nlines(raw.decode("utf-8")), "bytes": len(raw)}
    for u in js_units(root):
        out["units"] += 1
        m = unit_metrics(u)
        out["fns"] += m["fns"]
        for k in ("long", "esc", "n1384"):
            if m[k]:
                out[k][u.path] = out[k].get(u.path, 0) + m[k]
        if m["error"]:
            out["errors"].append((u.path,) + m["error"])
    out["fns"].sort(key=lambda f: (f["file"], f["start"], f["end"], f["qual"]))
    return out


_PY_NUM = re.compile(r"(?<![\w.])(?:0[xXoObB][0-9a-fA-F_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?)")


def py_1384(root: str) -> dict:
    out = {}
    for top in ("src", "tools"):
        for dp, dn, fns in os.walk(os.path.join(root, top)):
            dn[:] = sorted(d for d in dn if d != "__pycache__")
            for fn in sorted(fns):
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                text = _read(p)
                if not any(_num_val(m.group()) == 1384 for m in _PY_NUM.finditer(text)):
                    continue
                n = 0
                for t in _pytok.generate_tokens(io.StringIO(text).readline):
                    if t.type == _pytok.NUMBER and not t.string.lower().endswith("j") and _num_val(t.string) == 1384:
                        n += 1
                if n:
                    out[_rel(root, p)] = n
    return out
