from __future__ import annotations

import os
import re
from collections import namedtuple

import _sec_lint as L

Site = namedtuple("Site", "file line fn detail")
_ASSIGN = {"=", "+=", "-=", "||=", "&&=", "??="}
_SINK_PROPS = ("innerHTML", "outerHTML", "srcdoc")
_SINK_CALLS = ("insertAdjacentHTML", "createContextualFragment", "parseFromString", "setHTMLUnsafe", "setHTML")
_GLOBALS = ("window", "globalThis", "self")
_GLOBAL_WRITERS = ("assign", "defineProperties", "set", "setPrototypeOf", "defineProperty")


def _strs(t):
    if t.k == "str":
        return [t.v]
    if t.k == "tpl":
        return list(t.q or ())
    return []


def _cstr(t):
    if t.k == "str":
        return t.v
    if t.k == "tpl" and not t.x and t.q and len(t.q) == 1:
        return t.q[0]
    return None


def _encl(toks):
    st, out = [], []
    for t in toks:
        out.append(tuple(st))
        if t.k == "pun" and t.v in ("(", "[", "{"):
            st.append(len(out) - 1)
        elif t.k == "pun" and t.v in (")", "]", "}") and st:
            st.pop()
    return out


def _in_target(toks, mb, encl, i):
    n = len(toks)
    for o in reversed(encl[i]):
        c = mb.get(o)
        if toks[o].v in ("[", "{") and c is not None and c + 1 < n and toks[c + 1].k == "pun" and toks[c + 1].v == "=":
            return True
        if toks[o].v == "(" and o and toks[o - 1].v == "for" and i + 1 < n and toks[i + 1].v in ("of", "in"):
            return True
    return False


def _scan(unit, src, toks, out, outer=None):
    mb = L.match_brackets(toks)
    encl = _encl(toks)
    ctxs = L.js_contexts(toks, mb)
    n = len(toks)

    def fn(i):
        c = L.ctx_at(ctxs, i)
        return outer if (c == "<top>" and outer) else c

    def add(kind, i, detail=""):
        out.setdefault(kind, []).append(Site(unit, src.count("\n", 0, toks[i].p) + 1, fn(i), detail))

    for i, t in enumerate(toks):
        if t.k == "tpl":
            for ex in t.x or ():
                _scan(unit, src, ex, out, fn(i))
        for s in _strs(t):
            if re.search(r"<style\b", s, re.I):
                add("dynstyle", i, "문자열 '<style'")
            if "cdn.jsdelivr.net" in s:
                add("cdn", i, "cdn.jsdelivr.net")
        cs = _cstr(t)
        if cs is not None and i >= 1 and toks[i - 1].v == "[" and i + 2 < n and toks[i + 1].v == "]":
            if cs in _SINK_PROPS and toks[i + 2].k == "pun" and toks[i + 2].v in _ASSIGN:
                add("sink", i, "['%s'] %s" % (cs, toks[i + 2].v))
            elif cs in _SINK_CALLS and toks[i + 2].v in ("(", "?."):
                add("sink", i, "['%s']()" % cs)
            elif cs == "createPolicy":
                add("policy", i, "<동적>")
            elif cs in _SINK_CALLS:
                add("sink", i, "['%s'] 참조" % cs)
            elif cs in _SINK_PROPS:
                pass
        elif cs is not None and cs in _SINK_PROPS + _SINK_CALLS:
            add("sink", i, "글자 '%s'" % cs)
        elif cs == "createPolicy":
            add("policy", i, "<동적>")
        if t.k != "name":
            continue
        pv = toks[i - 1] if i else None
        nx = toks[i + 1] if i + 1 < n else None
        dotted = pv is not None and pv.k == "pun" and pv.v in (".", "?.")
        call = nx is not None and nx.v == "("
        a0 = _cstr(toks[i + 2]) if call and i + 2 < n else None
        if t.v in _SINK_PROPS and not dotted and nx is not None and nx.v == ":" and pv is not None and pv.v in ("{", ","):
            add("sink", i, "열쇠 %s:" % t.v)
        elif dotted and t.v in _SINK_PROPS and nx is not None and nx.k == "pun" and nx.v in _ASSIGN:
            add("sink", i, "%s %s" % (t.v, nx.v))
        elif dotted and t.v in _SINK_PROPS and _in_target(toks, mb, encl, i):
            add("sink", i, "%s 구조 분해·for 대상" % t.v)
        elif dotted and t.v in _SINK_CALLS:
            add("sink", i, t.v + ("()" if call else " 참조"))
        elif dotted and t.v in ("write", "writeln") and i >= 2 and toks[i - 2].v == "document":
            add("sink", i, "document.%s%s" % (t.v, "()" if call else " 참조"))
        elif t.v == "setAttribute" and dotted and call and (a0 or "").lower() == "srcdoc":
            add("sink", i, "setAttribute('srcdoc')")
        elif t.v == "createElement" and call and (a0 or "").lower() == "style" and i + 3 < n and toks[i + 3].v == ")":
            add("dynstyle", i, "createElement('style')")
        elif t.v == "setAttribute" and dotted and call and (a0 or "").lower() == "style":
            add("setattr_style", i, "setAttribute('style')")
        elif t.v == "createPolicy":
            add("policy", i, a0 if a0 is not None and i + 3 < n and toks[i + 3].v in (",", ")") else "<동적>")
        elif unit == "tjdom.js" and t.v in _GLOBALS and not dotted:
            k2 = toks[i + 2] if i + 2 < n else None
            k3 = toks[i + 3] if i + 3 < n else None
            asg3 = k3 is not None and k3.k == "pun" and k3.v in _ASSIGN
            ok = nx is not None and nx.v in (".", "?.") and k2 is not None and k2.k == "name" and (
                (k2.v == "TJDOM" and nx.v == "." and asg3 and k3.v == "=") or (k2.v == "trustedTypes" and not asg3))
            if ok and k2.v == "TJDOM":
                add("global", i, "TJDOM")
            elif not ok:
                nm = k2.v if nx is not None and nx.v == "." and k2 is not None and k2.k == "name" else "<계산>"
                add("global", i, "%s(전역 객체 %s 의 허용 밖 쓰임)" % (nm, t.v))
        elif t.v in _GLOBALS and not dotted and nx is not None and nx.v in (".", "["):
            if nx.v == "." and i + 3 < n and toks[i + 2].k == "name" and toks[i + 3].k == "pun" and toks[i + 3].v in _ASSIGN:
                add("global", i, toks[i + 2].v)
            elif nx.v == "[" and (i + 1) in mb:
                j = mb[i + 1]
                if j + 1 < n and toks[j + 1].k == "pun" and toks[j + 1].v in _ASSIGN:
                    inner = toks[i + 2:j]
                    add("global", i, inner[0].v if len(inner) == 1 and inner[0].k == "str" else "<계산>")
        elif t.v == "defineProperty" and dotted and call and i + 2 < n and toks[i + 2].k == "name" and toks[i + 2].v in _GLOBALS:
            a = toks[i + 4] if i + 4 < n and toks[i + 3].v == "," else None
            add("global", i, a.v if a is not None and a.k == "str" and i + 5 < n and toks[i + 5].v == "," else "<계산>")
        elif t.v in _GLOBAL_WRITERS and dotted and call and i + 2 < n and toks[i + 2].k == "name" and toks[i + 2].v in _GLOBALS \
                and i + 3 < n and toks[i + 3].v in (",", ")"):
            add("global", i, "<계산>")
        elif unit == "app.js" and dotted and t.v == "src" and nx is not None and nx.k == "pun" and nx.v == "=" \
                and not (i + 2 < n and toks[i + 2].k == "pun" and toks[i + 2].v in ("{", "[")):
            add("logo_src", i, "img.src =")


def _top_globals(unit, src, toks, out):
    n = len(toks)
    ctl = {"if", "for", "while", "switch", "catch", "with"}
    expr_prev = {"(", "=", ",", ":", "?", "!", "[", "&&", "||", "??", "return", "=>", "+", "-", "*", "/", "%", "~", "typeof", "void",
                 "new", "await", "yield", "in", "of", "+=", "-=", "||=", "&&=", "??=", "<", ">", "==", "===", "!=", "!=="}
    var_st, this_st, opens, pend_class = [], [], [], []

    def add(i, name):
        out.setdefault("global", []).append(Site(unit, src.count("\n", 0, toks[i].p) + 1, "<top>", name))

    paren_of = {}
    for i, t in enumerate(toks):
        if t.k == "pun" and t.v == "(":
            opens.append(i)
        elif t.k == "pun" and t.v == ")" and opens:
            paren_of[i] = opens.pop()
    for i, t in enumerate(toks):
        pv = toks[i - 1] if i else None
        if t.k == "name" and t.v == "class":
            pend_class.append(len(var_st))
        if t.k == "pun" and t.v in ("(", "[", "{"):
            fn_var = fn_this = False
            if t.v == "{" and pend_class and pend_class[-1] == len(var_st):
                pend_class.pop()
                fn_var = fn_this = True
            elif t.v == "{" and pv is not None:
                if pv.v == "=>":
                    fn_var = True
                elif pv.k == "name" and pv.v == "static":
                    fn_var = fn_this = True
                elif pv.v == ")" and (i - 1) in paren_of:
                    o = paren_of[i - 1]
                    fn_var = fn_this = not (o and toks[o - 1].k == "name" and toks[o - 1].v in ctl)
            var_st.append(fn_var)
            this_st.append(fn_this)
            continue
        if t.k == "pun" and t.v in (")", "]", "}"):
            if var_st:
                var_st.pop()
                this_st.pop()
            continue
        if t.k != "name":
            continue
        nx = toks[i + 1] if i + 1 < n else None
        if t.v == "this" and not any(this_st):
            nm = toks[i + 2].v if nx is not None and nx.v in (".", "?.") and i + 2 < n and toks[i + 2].k == "name" else "<계산>"
            add(i, "%s(함수 밖 this — 전역 객체)" % nm)
            continue
        if any(var_st):
            continue
        depth0 = not var_st
        if (t.v == "var" or (depth0 and t.v in ("let", "const"))) and nx is not None and not (pv is not None and pv.v in (".", "?.")):
            j = i + 1
            while j < n:
                if toks[j].k == "name":
                    add(i, toks[j].v)
                    j += 1
                else:
                    add(i, "<계산>")
                    if toks[j].v in ("{", "["):
                        d, j = 1, j + 1
                        while j < n and d:
                            d += 1 if toks[j].v in ("(", "[", "{") else -1 if toks[j].v in (")", "]", "}") else 0
                            j += 1
                d = 0
                while j < n and not (d == 0 and toks[j].v in (",", ";")):
                    if toks[j].v in ("(", "[", "{"):
                        d += 1
                    elif toks[j].v in (")", "]", "}"):
                        d -= 1
                    if d < 0:
                        break
                    j += 1
                if j >= n or toks[j].v != ",":
                    break
                j += 1
        elif t.v in ("function", "class") and not (pv is not None and pv.v in expr_prev):
            k = i + 1
            if k < n and toks[k].v == "*":
                k += 1
            add(i, toks[k].v if k < n and toks[k].k == "name" else "<계산>")


def _markup(root, name, out):
    p = os.path.join(root, "web", "v2", name)
    if not os.path.isfile(p):
        return
    with open(p, encoding="utf-8") as f:
        html = f.read()
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # noqa: E731
    mk = re.sub(r"<script\b[^>]*>.*?</script>", blank, html, flags=re.S | re.I)
    for m in re.finditer(r"<style\b[^>]*>.*?</style>", mk, re.S | re.I):
        out.setdefault("style_block", []).append(Site(name, mk.count("\n", 0, m.start()) + 1, "<markup>", "%d자" % (m.end() - m.start())))
    mk = re.sub(r"<style\b[^>]*>.*?</style>", blank, mk, flags=re.S | re.I)
    for m in re.finditer(r"<[A-Za-z][^>]*>", mk):
        for x in re.finditer(r"\sstyle\s*=", m.group(0)):
            out.setdefault("markup_style", []).append(Site(name, mk.count("\n", 0, m.start() + x.start()) + 1, "<markup>", "style 속성"))


def _ident_escapes(unit, src, toks, out):
    for t in toks:
        if t.k == "tpl":
            for ex in t.x or ():
                _ident_escapes(unit, src, ex, out)
        if t.k == "name" and ((t.p + len(t.v) < len(src) and src[t.p + len(t.v)] == "\\") or (t.p and src[t.p - 1] == "\\")):
            out.setdefault("ident_escape", []).append(Site(unit, src.count("\n", 0, t.p) + 1, "<?>", t.v))


def census(root):
    out = {k: [] for k in ("sink", "dynstyle", "setattr_style", "policy", "global", "logo_src", "cdn", "markup_style", "style_block", "ident_escape")}
    for unit, src in L.js_units(root):
        toks, _ = L.js_tokens(src)
        _scan(unit, src, toks, out)
        _ident_escapes(unit, src, toks, out)
        if unit == "tjdom.js":
            _top_globals(unit, src, toks, out)
    for h in ("index.html", "login.html"):
        _markup(root, h, out)
    return out


def by_file(sites):
    out = {}
    for s in sites:
        out[s.file] = out.get(s.file, 0) + 1
    return dict(sorted(out.items()))
