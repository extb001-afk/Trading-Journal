import ast
import hashlib
import json
import os
import re
import sys

import _sec_succession as SUCC

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(HERE, "arch_baseline")
UPDATE_LOWER = "--update-lower" in sys.argv


def _env_flag(name):
    return os.environ.get(name) == "1" or os.environ.get("TJ_TEST_" + name[3:]) == "1"


STALE_FAIL = _env_flag("TJ_ARCH_STALE_FAIL")
REQUIRE_NODE = _env_flag("TJ_REQUIRE_NODE")
BASELINE_INIT = _env_flag("TJ_SEC_BASELINE_INIT")
BASE_REF = os.environ.get("TJ_ARCH_BASE_REF") or os.environ.get("TJ_TEST_ARCH_BASE_REF") or ""


def _bpath(name):
    return os.path.join(BASE_DIR, "sec_%s.jsonl" % name)


def parse_baseline(text):
    out = {"_doc": "", "metrics": {}}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        if "_doc" in d:
            out["_doc"] = d["_doc"]
        else:
            out["metrics"].setdefault(d["m"], {})[d["k"]] = int(d["n"])
    return out


def load_baseline(name):
    try:
        with open(_bpath(name), encoding="utf-8") as f:
            return parse_baseline(f.read())
    except FileNotFoundError:
        return None


def save_baseline(name, data):
    os.makedirs(BASE_DIR, exist_ok=True)
    rows = [json.dumps({"_doc": data.get("_doc", "")}, ensure_ascii=False)]
    for m in sorted(data.get("metrics") or {}):
        for k, v in sorted((data["metrics"][m] or {}).items()):
            if int(v) > 0:
                rows.append(json.dumps({"m": m, "k": k, "n": int(v)}, ensure_ascii=False))
    with open(_bpath(name), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")


_GIT = {}


def _git(*args):
    import subprocess
    try:
        r = subprocess.run(["git", "-C", HERE] + list(args), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


SKIP_REF = ("skip", "none", "off", "0")


GIT_ENV_HARMLESS = frozenset({"GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_ASKPASS", "GIT_TERMINAL_PROMPT", "GIT_SSH", "GIT_SSH_COMMAND",
                              "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"})


def _git_meta(d):
    return os.path.lexists(os.path.join(d, ".git")) or (
        os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects")) and os.path.isdir(os.path.join(d, "refs")))


def _repo_near():
    starts = [HERE]
    if os.environ.get("TJ_TEST_ROOT"):
        starts.append(os.path.abspath(os.environ["TJ_TEST_ROOT"]))
    starts += [os.path.realpath(x) for x in starts]
    import subprocess
    for d in starts:
        try:
            if subprocess.run(["git", "-C", d, "rev-parse", "--git-dir"], capture_output=True, timeout=30).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        while True:
            if _git_meta(d):
                return True
            up = os.path.dirname(d)
            if up == d:
                break
            d = up
    return False


def skip_without_git():
    return (BASE_REF.strip().lower() in SKIP_REF and not any(k.startswith("GIT_") and k not in GIT_ENV_HARMLESS for k in os.environ)
            and not _repo_near())


def base_ref():
    if "ref" not in _GIT:
        top = _git("rev-parse", "--show-toplevel")
        if not top and skip_without_git():
            _GIT.update(ref=None, top="TJ_ARCH_BASE_REF=%s 명시 · git 저장소 아님" % BASE_REF, skip=True)
        elif not top:
            _GIT.update(ref=None, top="git 저장소 아님(공개 배치 등)")
        elif BASE_REF:
            ok = _git("rev-parse", "--verify", "-q", BASE_REF + "^{commit}")
            _GIT.update(ref=ok.strip() if ok else None, top=top.strip() if ok else "TJ_ARCH_BASE_REF=%s 를 못 찾음" % BASE_REF)
        elif _git("rev-parse", "--verify", "-q", "refactor^{commit}"):
            mb = _git("merge-base", "HEAD", "refactor")
            _GIT.update(ref=mb.strip() if mb else None, top=top.strip() if mb else "merge-base 없음")
        else:
            _GIT.update(ref=None, top="refactor 브랜치 없음")
    return _GIT["ref"], _GIT["top"]


_REF_CHECKED = []


def check_base_ref(T):
    if _REF_CHECKED:
        return
    _REF_CHECKED.append(1)
    ref, why = base_ref()
    if _GIT.get("skip"):
        print("SKIP %s — 기준 커밋 비교 건너뜀" % why, flush=True)
    elif BASE_REF and ref is None:
        T.chk(False, "TJ_ARCH_BASE_REF=%s 를 못 찾음 — 기준 커밋 비교를 못 함(설정 실수)" % BASE_REF, why)


def base_ref_baseline(name):
    ref, top = base_ref()
    if not ref:
        return None, None, top
    relp = os.path.relpath(_bpath(name), top).replace(os.sep, "/")
    out = _git("show", "%s:%s" % (ref, relp))
    if out is None:
        return ref, None, "그 커밋에 기준선 없음(처음 생김)"
    try:
        return ref, parse_baseline(out), ""
    except (ValueError, KeyError, TypeError):
        return ref, None, "그 커밋의 기준선을 못 읽음"


def ref_violations(name, bm, rbm, modes, work):
    bad = []
    for m in sorted(set(bm) | set(rbm)):
        viol, _dec, _mv, _succ = compare_succ(name, m, bm, rbm, modes.get(m, "site"), None, work)
        bad += ["%s · %s: 기준선 %d > 기준 커밋 %d" % (m, k, c, b) for k, c, b in viol]
    return bad


def _check_vs_ref(T, name, bm, modes, work):
    ref, rb, why = base_ref_baseline(name)
    if ref is None or rb is None:
        print("(기준선 %s: 기준 커밋 비교 건너뜀 — %s)" % (name, why))
        return
    bad = ref_violations(name, bm, rb.get("metrics") or {}, modes, work)
    T.chk(not bad, "[%s] 기준선 파일이 기준 커밋(%s)보다 늘지 않음 — 기준선은 줄이기만(--update-lower)" % (name, ref[:10]), bad[:12])


def _fname(k):
    return k.split("::", 1)[1] if "::" in k else k


def _file_of(k):
    return k.split("::", 1)[0]


def compare(cur, base, mode="site", exists=None):
    cur = {k: int(v) for k, v in cur.items() if int(v) > 0}
    base = {k: int(v) for k, v in base.items() if int(v) > 0}
    present = (lambda k: True) if exists is None else (lambda k: exists(_file_of(k)))
    if mode == "exact":
        viol = [(k, cur[k], base.get(k, 0)) for k in sorted(cur) if cur[k] > base.get(k, 0)]
        return viol, sorted(k for k in base if base[k] > cur.get(k, 0) and present(k)), []
    if mode == "total":
        sc, sb_all = sum(cur.values()), sum(base.values())
        sb_here = sum(v for k, v in base.items() if present(k) or k in cur)
        if sc > sb_all:
            new = sorted(k for k in cur if cur[k] > base.get(k, 0))
            return [("(합계)", sc, sb_all)] + [(k, cur[k], base.get(k, 0)) for k in new], [], []
        return [], (["(합계)"] if sc < sb_here else []), []
    spare = {k: base[k] - cur.get(k, 0) for k in base if base[k] > cur.get(k, 0)}
    viol, moved = [], []
    for k in sorted(cur):
        extra = cur[k] - base.get(k, 0)
        if extra <= 0:
            continue
        for same_file in (False, True):
            for k2 in sorted(spare):
                if extra <= 0:
                    break
                if k2 == k or spare[k2] <= 0:
                    continue
                if (not same_file and _fname(k2) == _fname(k) and _file_of(k2) != _file_of(k)) or \
                        (same_file and "::" in k and _file_of(k2) == _file_of(k)):
                    n = min(extra, spare[k2])
                    spare[k2] -= n
                    extra -= n
                    moved.append((k, k2, n))
        if extra > 0:
            viol.append((k, cur[k], base.get(k, 0)))
    dec = sorted(k for k, v in spare.items() if v > 0 and present(k))
    return viol, dec, moved


def compare_succ(name, m, side, base, mode="site", exists=None, work=None):
    v = SUCC.judge(name, m, side, base, side if work is None else work)
    viol, dec, moved = compare(v.side, v.base, mode, exists)
    viol = viol + [("%s(승계 거부: %s)" % (k, why), c, b) for k, c, b, why in v.bad]
    return viol, (sorted(dec + v.dec) if v.dec else dec), moved, v.granted


def ratchet(T, name, metrics, doc, hints=None, exists=None, modes=None, samples=None):
    hints, modes, samples = hints or {}, modes or {}, samples or {}
    check_base_ref(T)
    base = load_baseline(name)
    if base is None:
        ref, rb, _why = base_ref_baseline(name)
        if rb is not None:
            T.chk(False, "[%s] 기준선 파일이 없어짐(기준 커밋 %s 에는 있음) — 지우지 말고 --update-lower 로만 낮추세요" % (name, ref[:10]))
            return False
        if BASELINE_INIT:
            save_baseline(name, {"_doc": doc, "metrics": {m: {k: v for k, v in sorted(c.items()) if v} for m, c in metrics.items()}})
            print("(기준선 새로 만듦: %s)" % os.path.relpath(_bpath(name), HERE))
            return True
        print("(기준선 %s 없음 — 비교 건너뜀 · 공개 배치면 정상)" % os.path.relpath(_bpath(name), HERE))
        return False
    bm = base.get("metrics") or {}
    _check_vs_ref(T, name, bm, modes, metrics)
    all_ok, any_dec, new_bm = True, False, {}
    for m in sorted(set(metrics) | set(bm)):
        cur = metrics.get(m, {})
        b = bm.get(m, {})
        viol, dec, moved, succ = compare_succ(name, m, metrics, bm, modes.get(m, "site"), exists, metrics)
        tot_c, tot_b = sum(cur.values()), sum(b.values())
        if viol:
            all_ok = False
            lines = []
            for k, c, bb in viol[:12]:
                ex = (samples.get(m) or {}).get(k) or []
                lines.append("%s: 지금 %d > 기준 %d%s" % (k, c, bb, (" · 예: " + " | ".join(ex[:3])) if ex else ""))
            T.chk(False, "[%s] %s 늘었음 — %s" % (name, m, hints.get(m, "새 자리를 고치거나 기존 패턴으로 바꾸세요")), lines)
        else:
            T.chk(True, "[%s] %s 늘지 않음(지금 %d · 기준 %d%s%s)" % (name, m, tot_c, tot_b, (" · 옮김 %d" % sum(x[2] for x in moved)) if moved else "",
                                                                  (" · 승계 %d" % sum(succ.values())) if succ else ""))
        if succ:
            print("안내 [%s] %s 승계 인정(8막 3장 ⑨ — _sec_succession): %s" % (name, m, ", ".join(sorted(succ))[:300]))
        if dec:
            any_dec = True
            print("안내 [%s] %s 줄었음(좋음): %s" % (name, m, ", ".join(dec[:8]) + (" …" if len(dec) > 8 else "")))
        if moved:
            print("안내 [%s] %s 옮김: %s" % (name, m, ", ".join("%s ← %s" % (a, b2) for a, b2, _n in moved[:6])))
        new_bm[m] = {k: v for k, v in sorted(cur.items()) if v > 0}
    if any_dec and not UPDATE_LOWER:
        msg = "기준선보다 줄었어요 — `python3 %s --update-lower` 로 기준선을 낮추세요" % os.path.relpath(sys.argv[0], os.getcwd())
        if STALE_FAIL:
            T.chk(False, "[%s] %s(TJ_ARCH_STALE_FAIL=1)" % (name, msg))
        else:
            print("안내 [%s] %s" % (name, msg))
    if UPDATE_LOWER:
        if all_ok:
            out = dict(base)
            out["metrics"] = new_bm
            out["_doc"] = doc
            save_baseline(name, out)
            print("(기준선 낮춤: %s)" % os.path.relpath(_bpath(name), HERE))
        else:
            T.chk(False, "[%s] --update-lower 거부 — 늘어난 지표가 있어 기준선을 쓰지 않았어요(늘린 값은 기준선에 못 넣음)" % name)
    return True


def known_list(T, name, key, found, doc, hint):
    return ratchet(T, name, {key: {k: 1 for k in found}}, doc, hints={key: hint}, modes={key: "exact"})


def require_node(T, what):
    import subprocess
    n = T.node_path()
    if n:
        try:
            v = subprocess.run([n, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = "?"
        print("(node %s — %s)" % (v, what))
        return n
    if T.node_required(REQUIRE_NODE):
        T.chk(False, "node 없음 — %s 못 돌림(TJ_TEST_REQUIRE_NODE=1)" % what)
    else:
        print("SKIP node 없음 — %s 건너뜀" % what)
    return None


class Tok:
    __slots__ = ("k", "v", "p", "q", "x")

    def __init__(self, k, v, p, q=None, x=None):
        self.k, self.v, self.p, self.q, self.x = k, v, p, q, x

    def __repr__(self):
        return "Tok(%s,%r)" % (self.k, self.v if self.k != "tpl" else self.q)


_ID = re.compile(r"[A-Za-z_$\u0080-￿][\w$\u0080-￿]*")
_NUM = re.compile(r"(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?)n?")
_PUN = re.compile(r">>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|&&=|\|\|=|\?\?=|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.(?!\d)|\+\+|--|\+=|-=|\*=|/=|%=|&="
                  r"|\|=|\^=|<<|>>|\*\*|[{}()\[\];,<>+\-*/%&|^!~?:=.@#]")
_WS = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)+", re.S)
_RX_BEFORE = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"}
_ESC_MAP = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _unesc(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            d = s[i + 1]
            if d == "u" and s[i + 2:i + 3] == "{":
                j = s.find("}", i + 3)
                try:
                    out.append(chr(int(s[i + 3:j], 16)))
                except ValueError:
                    out.append("?")
                i = j + 1
                continue
            if d == "u":
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                except ValueError:
                    out.append("?")
                i += 6
                continue
            if d == "x":
                try:
                    out.append(chr(int(s[i + 2:i + 4], 16)))
                except ValueError:
                    out.append("?")
                i += 4
                continue
            if d == "\n":
                i += 2
                continue
            out.append(_ESC_MAP.get(d, d))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _regex_ok(prev):
    if prev is None:
        return True
    if prev.k == "pun":
        return prev.v not in (")", "]", "}")
    if prev.k == "name":
        return prev.v in _RX_BEFORE
    return False


def js_tokens(src, i=0, stop_brace=False):
    toks, n, depth, prev = [], len(src), 0, None
    while i < n:
        m = _WS.match(src, i)
        if m:
            i = m.end()
            if i >= n:
                break
        c = src[i]
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    break
                j += 1
            t = Tok("str", _unesc(src[i + 1:j]), i)
            i = j + 1
        elif c == "`":
            quasis, exprs, j, buf = [], [], i + 1, []
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src.startswith("${", j):
                    quasis.append(_unesc("".join(buf)))
                    buf = []
                    sub, j = js_tokens(src, j + 2, stop_brace=True)
                    exprs.append(sub)
                    j += 1
                    continue
                buf.append(src[j])
                j += 1
            quasis.append(_unesc("".join(buf)))
            t = Tok("tpl", None, i, quasis, exprs)
            i = j + 1
        elif c == "/" and _regex_ok(prev):
            j, cls = i + 1, False
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "[":
                    cls = True
                elif d == "]":
                    cls = False
                elif d == "/" and not cls:
                    break
                elif d == "\n":
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            t = Tok("rx", src[i:j], i)
            i = j
        else:
            m = _ID.match(src, i)
            if m:
                t = Tok("name", m.group(0), i)
                i = m.end()
            else:
                m = _NUM.match(src, i) if (c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit())) else None
                if m and m.end() > i:
                    t = Tok("num", m.group(0), i)
                    i = m.end()
                else:
                    m = _PUN.match(src, i)
                    if not m:
                        i += 1
                        continue
                    v = m.group(0)
                    if stop_brace:
                        if v == "{":
                            depth += 1
                        elif v == "}":
                            if depth == 0:
                                return toks, i
                            depth -= 1
                    t = Tok("pun", v, i)
                    i = m.end()
        toks.append(t)
        prev = t
    return toks, i


_OPEN, _CLOSE = {"(": ")", "[": "]", "{": "}"}, {")": "(", "]": "[", "}": "{"}


def match_brackets(toks):
    st, m = [], {}
    for i, t in enumerate(toks):
        if t.k != "pun":
            continue
        if t.v in _OPEN:
            st.append(i)
        elif t.v in _CLOSE:
            while st and toks[st[-1]].v != _CLOSE[t.v]:
                st.pop()
            if st:
                j = st.pop()
                m[i], m[j] = j, i
    return m


_KW = {"if", "for", "while", "switch", "catch", "with", "function", "return", "typeof", "new", "delete", "void", "await", "yield",
       "else", "do", "try", "finally", "case", "default", "in", "of", "instanceof", "var", "let", "const", "class", "extends", "super",
       "this", "null", "true", "false", "undefined", "throw", "break", "continue", "import", "export", "static", "get", "set", "async"}


def _expr_end(toks, i, mb):
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.k == "pun":
            if t.v in _OPEN:
                j = mb.get(i)
                if j is None:
                    return n
                i = j + 1
                continue
            if t.v in _CLOSE or t.v in (",", ";"):
                return i
        i += 1
    return n


def _assign_name(toks, j):
    if j >= 1 and toks[j].k == "pun" and toks[j].v in ("=", ":") and toks[j - 1].k in ("name", "str"):
        nm = toks[j - 1].v
        if toks[j - 1].k == "name" and nm in _KW:
            return None
        return nm if re.fullmatch(r"[\w$]+", nm or "") else None
    return None


def js_contexts(toks, mb=None):
    mb = mb if mb is not None else match_brackets(toks)
    out, n = [], len(toks)
    for i, t in enumerate(toks):
        if t.k == "name" and t.v == "function":
            j = i + 1
            if j < n and toks[j].v == "*":
                j += 1
            nm = toks[j].v if j < n and toks[j].k == "name" else None
            if nm:
                j += 1
            else:
                k = i - 1
                if k >= 0 and toks[k].k == "name" and toks[k].v == "async":
                    k -= 1
                nm = _assign_name(toks, k)
            if j < n and toks[j].v == "(" and j in mb:
                b = mb[j] + 1
                if b < n and toks[b].v == "{" and b in mb and nm:
                    out.append((b, mb[b], nm))
        elif t.k == "pun" and t.v == "=>":
            k = i - 1
            if k < 0:
                continue
            if toks[k].v == ")" and k in mb:
                k = mb[k] - 1
            elif toks[k].k == "name":
                k -= 1
            else:
                continue
            if k >= 0 and toks[k].k == "name" and toks[k].v == "async":
                k -= 1
            nm = _assign_name(toks, k)
            if not nm:
                continue
            b = i + 1
            if b < n and toks[b].v == "{" and b in mb:
                out.append((b, mb[b], nm))
            elif b < n:
                out.append((b, _expr_end(toks, b, mb), nm))
        elif t.k == "name" and t.v not in _KW and i + 1 < n and toks[i + 1].v == "(" and (i + 1) in mb:
            p = toks[i - 1] if i else None
            if p is not None and not (p.k == "pun" and p.v in ("{", ",", "}", ";")) and not (p.k == "name" and p.v in ("static", "async", "get", "set")):
                continue
            b = mb[i + 1] + 1
            if b < n and toks[b].v == "{" and b in mb:
                out.append((b, mb[b], t.v))
    return out


def ctx_at(ctxs, i):
    best = None
    for a, b, nm in ctxs:
        if a <= i <= b and (best is None or a > best[0]):
            best = (a, b, nm)
    return best[2] if best else "<top>"


def js_files(root):
    v2 = os.path.join(root, "web", "v2")
    return sorted(f for f in os.listdir(v2) if f.endswith(".js"))


_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def _html_script_text(html):
    buf = [c if c == "\n" else " " for c in html]
    for m in _SCRIPT_RE.finditer(html):
        a, b = m.span(1)
        buf[a:b] = list(html[a:b])
        if a:
            buf[a - 1] = ";"
    return "".join(buf)


def js_units(root):
    v2 = os.path.join(root, "web", "v2")
    out = []
    for f in js_files(root):
        out.append((f, open(os.path.join(v2, f), encoding="utf-8").read()))
    for h in ("index.html", "login.html"):
        p = os.path.join(v2, h)
        if os.path.isfile(p):
            html = open(p, encoding="utf-8").read()
            if _SCRIPT_RE.search(html):
                out.append((h, _html_script_text(html)))
    return out


def html_static(root):
    v2 = os.path.join(root, "web", "v2")
    out = []
    for h in ("index.html", "login.html"):
        p = os.path.join(v2, h)
        if os.path.isfile(p):
            out.append((h, re.sub(r"<script\b[^>]*>.*?</script>", "", open(p, encoding="utf-8").read(), flags=re.S | re.I)))
    return out


ESC_NAMES = {"esc", "esc0", "es", "xml", "escA", "escAttr", "escHtml", "escapeHtml", "htmlEsc"}
SAFE_URL_NAMES = set()
_NONDYN = {"true", "false", "null", "undefined", "NaN", "Infinity", "typeof", "void", "new", "in", "instanceof"}


def _region_skip(toks, i, mb, names):
    t = toks[i]
    if t.k == "name" and t.v in names and i + 1 < len(toks) and toks[i + 1].v == "(" and (i + 1) in mb:
        return mb[i + 1] + 1
    return None


_CMP = {"===", "!==", "==", "!=", "<", ">", "<=", ">="}
_TERN_STOP = {",", ";", "=", "+=", ":", "?", "=>", "(", "[", "{"}


def cond_positions(toks, mb=None):
    mb = mb if mb is not None else match_brackets(toks)
    cond, n = set(), len(toks)

    def chain_left(j):
        while j > 0:
            p = toks[j - 1]
            if p.k == "pun" and p.v in (".", "?."):
                j -= 2 if j >= 2 else 1
                continue
            if p.k == "pun" and p.v in ("]", ")") and (j - 1) in mb and j - 1 > 0:
                j = mb[j - 1]
                continue
            break
        return j

    def chain_right(j):
        while j + 1 < n:
            nx = toks[j + 1]
            if nx.k == "pun" and nx.v in (".", "?.") and j + 2 < n:
                j += 2
                continue
            if nx.k == "pun" and nx.v in ("[", "(") and (j + 1) in mb:
                j = mb[j + 1]
                continue
            break
        return j

    for q, t in enumerate(toks):
        if t.k != "pun":
            if t.k == "name" and t.v == "typeof" and q + 1 < n:
                cond.update(range(q + 1, chain_right(q + 1) + 1))
            continue
        if t.v == "?":
            j = q - 1
            while j >= 0:
                x = toks[j]
                if x.k == "pun" and x.v in _CLOSE and j in mb:
                    j = mb[j] - 1
                    continue
                if (x.k == "pun" and x.v in _TERN_STOP) or (x.k == "name" and x.v in ("return", "case")):
                    break
                j -= 1
            cond.update(range(j + 1, q))
        elif t.v in _CMP:
            if q > 0:
                cond.update(range(chain_left(q - 1), q))
            if q + 1 < n:
                cond.update(range(q + 1, chain_right(q + 1) + 1))
        elif t.v == "!" and q + 1 < n:
            cond.update(range(q + 1, chain_right(q + 1) + 1))
        elif t.v in (".", "?.") and q + 1 < n and toks[q + 1].k == "name" and toks[q + 1].v in ("length", "size"):
            cond.update(range(chain_left(q - 1) if q else 0, q + 2))
    return cond


def classify_expr(toks):
    mb = match_brackets(toks)
    cond = cond_positions(toks, mb)
    has_esc, dyn, i, n = False, [], 0, len(toks)
    while i < n:
        t = toks[i]
        if i in cond:
            i += 1
            continue
        j = _region_skip(toks, i, mb, ESC_NAMES | SAFE_URL_NAMES)
        if j is not None:
            has_esc = True
            i = j
            continue
        if t.k == "tpl":
            for ex in t.x or ():
                c, d = classify_expr(ex)
                if c == "raw":
                    dyn.append(d)
                elif c == "esc":
                    has_esc = True
        elif t.k == "name" and t.v not in _NONDYN:
            prev = toks[i - 1] if i else None
            if not (prev is not None and prev.k == "pun" and prev.v in (".", "?.")):
                dyn.append(t.v)
        i += 1
    if dyn:
        return "raw", dyn[0]
    return ("esc" if has_esc else "static"), ""


def _raw_kind(toks):
    mb = match_brackets(toks)
    if toks and toks[0].k == "name" and len(toks) >= 3 and toks[1].v == "(" and mb.get(1) == len(toks) - 1:
        return "call"
    if all(t.k == "name" or (t.k == "pun" and t.v in (".", "?.")) for t in toks):
        return "var"
    return "mix"


_HTML_MARK = re.compile(r"<[A-Za-z/!]|\s[\w:-]+=[\"']|=[\"']$")
_URL_ATTR = re.compile(r"(?:^|[\s\"'<])(href|src|action|formaction|xlink:href|poster|srcset|background|cite|ping|data)\s*=\s*([\"']?)([^\"'\s>]*)$", re.I)
_SAFE_PREFIX = re.compile(r"(?:#|\?|/(?!/)|\./|\.\./|https?://|mailto:|tel:|data:image/)", re.I)
_INLINE_HANDLER = re.compile(r"\son[a-z]{3,}\s*=", re.I)
_JS_URL = re.compile(r"(?:href|src|action|formaction|xlink:href)\s*=\s*[\"']?\s*(?:javascript|vbscript)\s*:", re.I)
EXT_FIELDS = {"sym", "symbol", "name", "label", "memo", "note", "alias", "title", "addr", "address", "msg", "message", "error", "err",
              "text", "desc", "description", "reason", "why", "detail", "tag", "venue", "pool", "dex", "url", "link", "docs",
              "bot", "chatName", "chat_name", "username", "comment", "pair", "symbol0", "symbol1", "sym0", "sym1", "token", "tokenName"}
_COND_NEXT = {"?", "===", "!==", "==", "!=", "<", ">", "<=", ">=", "&&", "in", "instanceof"}
_COND_PREV = {"!", "===", "!==", "==", "!=", "<", ">", "<=", ">=", "typeof"}


def _split_plus(toks, a, b, mb):
    parts, s, i = [], a, a
    while i < b:
        t = toks[i]
        if t.k == "pun" and t.v in _OPEN and i in mb:
            i = mb[i] + 1
            continue
        if t.k == "pun" and t.v == "+":
            parts.append((s, i))
            s = i + 1
        i += 1
    parts.append((s, b))
    return parts


def _ext_hits(toks, a, b, mb):
    hits, i = [], a
    while i < b:
        t = toks[i]
        if t.k == "name" and i + 1 < b and toks[i + 1].v == "(" and (i + 1) in mb:
            i = mb[i + 1] + 1
            continue
        if t.k == "pun" and t.v in (".", "?.") and i + 1 < b and toks[i + 1].k == "name" and toks[i + 1].v in EXT_FIELDS:
            nx = toks[i + 2] if i + 2 < b else None
            if nx is not None and nx.k == "pun" and (nx.v in ("(", ".", "?.", "[") or nx.v in _COND_NEXT or nx.v in ("=", "+=")):
                i += 2
                continue
            if nx is not None and nx.k == "name" and nx.v in ("in", "instanceof"):
                i += 2
                continue
            k = i - 1
            while k >= a and (toks[k].k == "name" or (toks[k].k == "pun" and toks[k].v in (".", "?."))):
                k -= 1
            pv = toks[k] if k >= a else None
            if pv is not None and ((pv.k == "pun" and pv.v in _COND_PREV) or (pv.k == "name" and pv.v == "typeof")):
                i += 2
                continue
            hits.append(toks[i + 1].v)
            i += 2
            continue
        i += 1
    return hits


def _arg_sig(toks):
    return " ".join("'%s'" % t.v if t.k == "str" else "`…`" if t.k == "tpl" else str(t.v) for t in toks)


def _url_kind(prefix, toks, safe=False):
    if prefix:
        return "prefixed" if _SAFE_PREFIX.match(prefix) else "raw"
    if not toks:
        return "static"
    mb = match_brackets(toks)
    if toks[0].k == "name" and toks[0].v in SAFE_URL_NAMES and len(toks) > 1 and toks[1].v == "(" and mb.get(1) == len(toks) - 1:
        return "safe"
    if safe:
        return "safe"
    if toks[0].k == "str":
        return "prefixed" if _SAFE_PREFIX.match(toks[0].v) else ("static" if len(toks) == 1 else "raw")
    if toks[0].k == "tpl" and toks[0].q and _SAFE_PREFIX.match(toks[0].q[0] or "x"):
        return "prefixed"
    c, _d = classify_expr(toks)
    if c == "static":
        return "static"
    if toks[0].k == "name" and toks[0].v in ESC_NAMES and len(toks) > 1 and toks[1].v == "(" and mb.get(1) == len(toks) - 1:
        return "esc_only"
    return "raw"


def js_scan(unit_name, src, sites=None, seen=None):
    toks, _ = js_tokens(src)
    out = []
    _scan_list(toks, unit_name, src, out, None, sites, seen)
    return out


def _line_of(src, p):
    return src.count("\n", 0, p) + 1


def _scan_list(toks, unit, src, out, outer_ctx, sites=None, seen=None):
    mb = match_brackets(toks)
    ctxs = js_contexts(toks, mb)
    n = len(toks)

    def ok(i, vt):
        key = _fn_key(toks, mb, ctxs, i) if outer_ctx is None and _has_safe_url(vt) else None
        if key and seen is not None:
            seen[key] = seen.get(key, 0) + 1
        return bool(key and sites and key in sites)

    def ctx(i):
        c = ctx_at(ctxs, i)
        return outer_ctx if (c == "<top>" and outer_ctx) else c

    def add(cat, i, detail=""):
        out.append((cat, ctx(i), detail, _line_of(src, toks[i].p) if i < n else 0))

    for i, t in enumerate(toks):
        if t.k == "tpl":
            for ex in t.x or ():
                _scan_list(ex, unit, src, out, ctx(i), sites, seen)
        if t.k == "name":
            nx = toks[i + 1] if i + 1 < n else None
            pv = toks[i - 1] if i else None
            dotted = pv is not None and pv.k == "pun" and pv.v in (".", "?.")
            if dotted and t.v in ("innerHTML", "outerHTML", "srcdoc") and nx is not None and nx.k == "pun" and nx.v in ("=", "+="):
                e = _expr_end(toks, i + 2, mb)
                rhs = toks[i + 2:e]
                c, d = classify_expr(rhs)
                add("sink:" + c, i, "%s%s %s" % (t.v, nx.v, (_raw_kind(rhs) + ":" + d) if c == "raw" else ""))
            elif t.v in ("insertAdjacentHTML", "createContextualFragment", "parseFromString", "setHTMLUnsafe") and dotted and nx is not None and nx.v == "(" and (i + 1) in mb:
                args = _split_args(toks, i + 1, mb)
                a = args[1] if t.v == "insertAdjacentHTML" and len(args) > 1 else (args[0] if args else [])
                c, d = classify_expr(a)
                add("sink:" + c, i, "%s() %s" % (t.v, (_raw_kind(a) + ":" + d) if c == "raw" else ""))
            elif t.v in ("write", "writeln") and dotted and i >= 2 and toks[i - 2].v == "document" and nx is not None and nx.v == "(" and (i + 1) in mb:
                args = _split_args(toks, i + 1, mb)
                c, d = classify_expr([x for a in args for x in a])
                add("sink:" + c, i, "document.%s() %s" % (t.v, d))
            elif t.v == "DOMParser" and pv is not None and pv.v == "new":
                add("sink:raw", i, "new DOMParser")
            elif t.v == "eval" and not dotted and nx is not None and nx.v == "(":
                add("code_sink", i, "eval()")
            elif t.v == "Function" and pv is not None and pv.v == "new":
                add("code_sink", i, "new Function")
            elif t.v in ("setTimeout", "setInterval") and nx is not None and nx.v == "(" and i + 2 < n and toks[i + 2].k in ("str", "tpl"):
                add("code_sink", i, t.v + "(문자열)")
            elif dotted and re.fullmatch(r"on[a-z]{3,}", t.v) and nx is not None and nx.v == "=" and i + 2 < n and toks[i + 2].k in ("str", "tpl"):
                add("code_sink", i, t.v + "=문자열")
            elif t.v == "setAttribute" and dotted and nx is not None and nx.v == "(" and (i + 1) in mb:
                args = _split_args(toks, i + 1, mb)
                a0 = args[0] if args else []
                attr = a0[0].v.lower() if len(a0) == 1 and a0[0].k == "str" else ""
                if attr.startswith("on") or attr == "srcdoc":
                    add("code_sink" if attr.startswith("on") else "sink:" + classify_expr(args[1] if len(args) > 1 else [])[0], i, "setAttribute(%s)" % attr)
                elif attr in ("href", "src", "action", "formaction", "xlink:href", "srcset", "poster") and len(args) > 1:
                    add("url:" + _url_kind("", args[1], ok(i, args[1])), i, "setAttribute(%s) ← %s" % (attr, _arg_sig(args[1])))
            elif dotted and t.v in ("href", "src", "srcset", "formAction") and nx is not None and nx.k == "pun" and nx.v == "=" \
                    and not (i + 2 < n and toks[i + 2].k == "pun" and toks[i + 2].v in ("{", "[")):
                e = _expr_end(toks, i + 2, mb)
                add("url:" + _url_kind("", toks[i + 2:e], ok(i, toks[i + 2:e])), i, "." + t.v + "= ← " + _arg_sig(toks[i + 2:e]))
            elif t.v == "location" and nx is not None and nx.k == "pun" and nx.v == "=":
                e = _expr_end(toks, i + 2, mb)
                add("url:" + _url_kind("", toks[i + 2:e], ok(i, toks[i + 2:e])), i, "location= ← " + _arg_sig(toks[i + 2:e]))
            elif dotted and t.v in ("assign", "replace") and i >= 2 and toks[i - 2].v == "location" and nx is not None and nx.v == "(" and (i + 1) in mb:
                args = _split_args(toks, i + 1, mb)
                add("url:" + _url_kind("", args[0] if args else [], ok(i, args[0] if args else [])), i, "location." + t.v + "() ← " + _arg_sig(args[0] if args else []))
            elif t.v == "open" and dotted and i >= 2 and toks[i - 2].v == "window" and nx is not None and nx.v == "(" and (i + 1) in mb:
                args = _split_args(toks, i + 1, mb)
                add("url:" + _url_kind("", args[0] if args else [], ok(i, args[0] if args else [])), i, "window.open() ← " + _arg_sig(args[0] if args else []))
        if t.k == "str" and t.v in ("innerHTML", "outerHTML", "srcdoc") and i >= 1 and toks[i - 1].v == "[" and i + 2 < n \
                and toks[i + 1].v == "]" and toks[i + 2].k == "pun" and toks[i + 2].v in ("=", "+="):
            e = _expr_end(toks, i + 3, mb)
            rhs = toks[i + 3:e]
            c, d = classify_expr(rhs)
            add("sink:" + c, i, "['%s']%s %s" % (t.v, toks[i + 2].v, (_raw_kind(rhs) + ":" + d) if c == "raw" else ""))
        if t.k == "str" and _HTML_MARK.search(t.v):
            if _INLINE_HANDLER.search(t.v) or _JS_URL.search(t.v):
                add("inline_handler", i, t.v[:40])
            m = _URL_ATTR.search(t.v)
            if m and i + 1 < n and toks[i + 1].v == "+":
                parts = _split_plus(toks, i + 2, _expr_end(toks, i + 2, mb), mb)
                a, b = parts[0]
                add("url:" + _url_kind(m.group(3), toks[a:b] if not m.group(3) else [], ok(i, toks[a:b])), i, "%s=" % m.group(1).lower())
        if t.k == "tpl":
            html9 = any(_HTML_MARK.search(q9) for q9 in t.q)
            for qi, q in enumerate(t.q[:-1]):
                m = _URL_ATTR.search(q)
                if m and html9:
                    add("url:" + _url_kind(m.group(3), t.x[qi] if not m.group(3) else [], ok(i, t.x[qi])), i, "%s=(템플릿)" % m.group(1).lower())
            if any(_HTML_MARK.search(q) for q in t.q):
                if any(_INLINE_HANDLER.search(q) or _JS_URL.search(q) for q in t.q):
                    add("inline_handler", i, "템플릿")
                for ex in t.x or ():
                    emb = match_brackets(ex)
                    for f in _ext_hits(ex, 0, len(ex), emb):
                        add("ext", i, "${…%s}" % f)
    _scan_concat_ext(toks, mb, ctx, add)


def _split_args(toks, i, mb):
    j = mb[i]
    args, s, k = [], i + 1, i + 1
    while k < j:
        t = toks[k]
        if t.k == "pun" and t.v in _OPEN and k in mb:
            k = mb[k] + 1
            continue
        if t.k == "pun" and t.v == ",":
            args.append(toks[s:k])
            s = k + 1
        k += 1
    if s < j:
        args.append(toks[s:j])
    return args


def _scan_concat_ext(toks, mb, ctx, add):
    n, seen = len(toks), set()
    for i, t in enumerate(toks):
        if t.k != "str" or not _HTML_MARK.search(t.v) or i in seen:
            continue
        a = i
        while a > 0:
            p = toks[a - 1]
            if p.k == "pun" and p.v in _CLOSE and (a - 1) in mb:
                a = mb[a - 1]
                continue
            if p.k == "pun" and (p.v in _OPEN or p.v in (",", ";", "=", "+=", "=>", "?", ":", "||", "&&", "??", "return") or p.v in _CLOSE):
                break
            if p.k == "name" and p.v in ("return", "case", "else", "do", "throw", "typeof", "void", "new", "in", "of", "await", "yield"):
                break
            a -= 1
        b = _expr_end(toks, i, mb)
        k = i
        while k < b:
            x = toks[k]
            if x.k == "pun" and x.v in _OPEN and k in mb:
                k = mb[k] + 1
                continue
            if x.k == "pun" and x.v in ("?", ":", "||", "&&", "??"):
                b = k
                break
            k += 1
        for s, e in _split_plus(toks, a, b, mb):
            for q in range(s, e):
                if toks[q].k == "str":
                    seen.add(q)
            if e - s == 1 and toks[s].k in ("str", "num"):
                continue
            for f in _ext_hits(toks, s, e, mb):
                add("ext", s, f)


SAFE_URL_OBJ, SAFE_URL_FN = "TJDOM", "safeUrl"
SAFE_URL_SCHEMES = ("blob", "data", "http", "https", "mailto", "tel")
SAFE_URL_DEFS = {
    "NAMED": "const NAMED = { colon: ':', tab: '\\t', newline: '\\n', sol: '/', period: '.', num: '#', quest: '?' };",
    "deRef": "function deRef(s) { return s.replace(/&(?:#(\\d+)|#[xX]([0-9a-fA-F]+)|([A-Za-z]+));?/g, (m, d, x, n) => {"
             " if (d || x) { const c = parseInt(d || x, d ? 10 : 16); return c > 0 && c < 0x110000 ? String.fromCodePoint(c) : ''; }"
             " const t = NAMED[n.toLowerCase()]; return t === undefined ? m : t; }); }",
    "scheme": "function scheme(s) { const t = s.replace(/^[\\u0000- ]+|[\\u0000- ]+$/g, '').replace(/[\\t\\n\\r]/g, '');"
              " const m = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(t); return { t, s: m ? m[1].toLowerCase() : '' }; }",
    "urlOk1": "function urlOk1(s, img) { const u = scheme(s); if (/[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]/.test(u.t)) return false;"
              " if (!u.s) return true; if (u.s === 'http' || u.s === 'https' || u.s === 'mailto' || u.s === 'tel') return true;"
              " if (u.s === 'blob') return u.t.slice(5, 6 + location.origin.length) === location.origin + '/';"
              " if (u.s === 'data') return !!img && /^data:image\\/(png|jpeg|gif|webp)[;,]/i.test(u.t); return false; }",
    "urlOk": "const urlOk = (v, img) => { const s = String(v); return urlOk1(s, img) && urlOk1(deRef(s), img); };",
    "safeUrl": "function safeUrl(u, kind) { if (u == null) return ''; return urlOk(u, kind === 'img') ? String(u) : '#'; }",
}
SAFE_URL_NAME_N = {"NAMED": 2, "deRef": 2, "scheme": 2, "urlOk1": 3, "urlOk": 3, "safeUrl": 2, "location": 2, "TJDOM": 3}
SAFE_URL_EXPORT = "window.TJDOM = Object.freeze({ set, insert, replace, clear, esc, safeUrl, report });"
SAFE_URL_OK = ["https://example.test/a/b?c=1&d=2#e", "http://example.test/", "https://example.test/p?q=\"x\"&r='y'&amp=1",
               "/v2/app.js?v=1&x=2", "./rel", "../up", "rel/path", "#settings/keys/exchanges", "?q=1&b=2", "",
               "mailto:someone@example.test", "tel:+82-10-0000-0000", "blob:https://tj.test/0000-1111"]
SAFE_URL_OK_IMG = ["data:image/png;base64,iVBORw0KGgo=", "https://example.test/i.png?a=1&b=2"]
_SAFE_URL_JS = r'''
const IN = JSON.parse(require('fs').readFileSync(0, 'utf8')), vm = require('vm');
// 실제 tjdom.js 를 가짜 창에서 실행 → 내보낸 TJDOM.safeUrl·esc 로 검사(뽑은 정의가 아니라 실제로 나가는 함수) · 내보낸 safeUrl 글 = 검증한 정의 글
const g = { location: { origin: 'https://tj.test' }, document: { implementation: { createHTMLDocument: () => ({}) } } };
g.window = g; vm.createContext(g); vm.runInContext(IN.full, g);
const F = g.TJDOM;
if (!F || String(F.safeUrl) !== IN.def) { console.log(JSON.stringify(['내보낸 TJDOM.safeUrl 이 검증한 정의와 다름'])); process.exit(0); }
const dec = s => s.replace(/&(amp|lt|gt|quot|#39);/g, (m, e) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" }[e]));
const bad = [];
const one = (u, k) => {
  const v = F.safeUrl(u, k);
  if (v !== u) bad.push('safeUrl 이 바꿈: ' + JSON.stringify(u));
  const m = /^<a href="([^"]*)">x<\/a>$/.exec('<a href="' + F.esc(v) + '">x</a>');
  if (!m || dec(m[1]) !== u) bad.push('속성 값이 원래 URL 과 다름: ' + JSON.stringify(u));
};
IN.ok.forEach(u => one(u)); IN.img.forEach(u => one(u, 'img'));
if (F.safeUrl(null) !== '' || F.safeUrl(undefined) !== '') bad.push('null·undefined → 빈 글 아님');
console.log(JSON.stringify(bad));
'''
_SAFE_URL_MEMO = {}


def _tok_sig(text):
    return [(t.k, t.v if t.k != "tpl" else tuple(t.q)) for t in js_tokens(text)[0]]


def safe_url_check(root, node=None):
    memo = (os.path.abspath(root), node)
    if memo in _SAFE_URL_MEMO:
        return _SAFE_URL_MEMO[memo]
    src = dict(js_units(root)).get(SUCC.TJDOM)
    probs, ran = [], False
    if src is None:
        probs.append("tjdom.js 없음")
    else:
        got = js_defs_all(src, list(SAFE_URL_DEFS))
        for nm, want in SAFE_URL_DEFS.items():
            ds = got.get(nm, [])
            if len(ds) != 1:
                probs.append("%s 정의 %d개(하나여야)" % (nm, len(ds)))
            elif _tok_sig(ds[0]) != _tok_sig(want):
                probs.append("%s 정의가 검증한 글과 다름(_sec_lint.SAFE_URL_DEFS)" % nm)
        sch = sorted(set(re.findall(r"u\.s === '([a-z]+)'", got.get("urlOk1", [""])[0] if got.get("urlOk1") else "")))
        if sch != sorted(SAFE_URL_SCHEMES):
            probs.append("urlOk1 스킴 표 %s ≠ 닫힌 표 %s" % (sch, list(SAFE_URL_SCHEMES)))
        sig, ex = _tok_sig(src), _tok_sig(SAFE_URL_EXPORT)
        at = [i for i in range(len(sig)) if sig[i:i + 3] == ex[:3]]
        if len(at) != 1 or sig[at[0]:at[0] + len(ex)] != ex:
            probs.append("전역 내보내기가 검증한 글(SAFE_URL_EXPORT)과 다름 또는 window.TJDOM 대입이 하나가 아님")
        nn = {}
        for t9 in _flat_names(js_tokens(src)[0]):
            if t9 in SAFE_URL_NAME_N:
                nn[t9] = nn.get(t9, 0) + 1
        if nn != SAFE_URL_NAME_N:
            probs.append("tjdom.js 안 URL 검사 이름 쓰임 수 %s ≠ 고정 표 SAFE_URL_NAME_N(다시 대입·가리기 의심)" % nn)
        bare = [u for u, t in js_units(root) if u != SUCC.TJDOM and not _tjdom_member_only(js_tokens(t)[0])]
        if bare:
            probs.append("tjdom.js 밖에서 맨 이름 TJDOM(멤버 접근 밖) 쓰임: %s" % bare)
        refs = ["%s:%d" % (u, n) for u, n in ((u, _tjdom_global_refs(js_tokens(t)[0])) for u, t in js_units(root)) if n]
        if refs != ["%s:1" % SUCC.TJDOM]:
            probs.append("전역 TJDOM 을 멤버·글자로 건드리는 곳이 내보내기 하나가 아님: %s" % refs)
        if node and not probs:
            import subprocess
            r = subprocess.run([node, "-e", _SAFE_URL_JS], input=json.dumps({"full": src, "def": got["safeUrl"][0], "ok": SAFE_URL_OK, "img": SAFE_URL_OK_IMG}),
                               capture_output=True, text=True, timeout=60)
            try:
                probs += json.loads(r.stdout.strip().splitlines()[-1])
                ran = True
            except (ValueError, IndexError):
                probs.append("카나리아 실행 실패: %s" % (r.stderr or r.stdout)[-300:])
    out = (not probs, probs, ran)
    _SAFE_URL_MEMO[memo] = out
    return out


_SEARCH_TITLE = "검색 항목 제목 = search.js 가 mark()·esc()·shortMark() 로 만든 HTML 조각(<mark>·알약 태그 · 서버 원문은 mark 가 이스케이프)"
_SAME_ORIGIN = "nextUrl() = 같은 출처 경로만('/' 시작 · '//'·'/\\'·공백·제어 글자·/login·/api 금지 — src/login_auth.safe_next 와 같은 규칙 · TJDOM 안 씀)"
EXT_ALLOW = {
    ("search.js", "rowHTML", "title"): (1, _SEARCH_TITLE),
    ("search.js", "paintBody", "title"): (1, _SEARCH_TITLE + " · exact = ST.flat 의 항목"),
    ("search.js", "paintPv", "title"): (1, _SEARCH_TITLE),
}
URL_ALLOW = {
    ("wow.js", "onload", ".href= ← u", "raw"): (1, "연말 결산 PNG 저장: cv.toBlob → URL.createObjectURL 이 만든 blob URL → 내려받기 a.href(생산자·소비자 고정)"),
    ("wow.js", "yeSave", ".src= ← 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent ( svg )", "prefixed"): (1, "연말 결산: yeSvg 가 xml() 로 만든 내부 SVG → data:image/svg+xml → Image → canvas(safeUrl data 허용은 안 넓힘)"),
    ("login.js", "boot", "location.replace() ← nextUrl ( )", "raw"): (1, _SAME_ORIGIN),
    ("login.js", "onLogin", "location.replace() ← nextUrl ( )", "raw"): (1, _SAME_ORIGIN),
    ("login.js", "onSetup", "location.replace() ← nextUrl ( )", "raw"): (1, _SAME_ORIGIN),
    ("index.html", "go", "location.replace() ← u", "raw"): (1, "TJDOM 보다 먼저 도는 머리 인라인(401 감시) · u = '/login' + ('?next=' + encodeURIComponent(같은 출처 경로))"
                                                           " — test_xss_lint [13] 이 u 정의를 고정"),
    ("index.html", "go", "location.replace() ← location . pathname + '#dash'", "raw"): (1, "TJDOM 없이 도는 부팅 감시 복구 카드(설계 4장 복구 경로) · 같은 문서 경로 + '#dash'"),
}


def _allow_cat(cat, unit, fn, detail):
    if cat == "ext":
        f = re.sub(r"^\$\{…|\}$", "", detail.strip())
        return "ext:allow" if (unit, fn, f) in EXT_ALLOW else cat
    if cat.startswith("url:") and (unit, fn, detail.strip(), cat[4:]) in URL_ALLOW:
        return "url:allow"
    return cat


SAFE_URL_SITES = {
    ("app.js", "resetPrefs", "50b850003c594b6f"): 1,
    ("salelink.js", "xl", "0f885e27c2bb20fb"): 1,
    ("search.js", "actBtn", "13d5c20ba50da525"): 1,
    ("search.js", "paintPv", "ab39aac8c743333f"): 1,
    ("setup.js", "exchangesHTML", "a86664cd72c7d3ad"): 1,
    ("setup.js", "keysHTML", "91765ae3d554b70d"): 1,
    ("setup.js", "permModalHTML", "2ce639635f89fecf"): 1,
    ("setup.js", "tgHTML", "c4552715856b5ea0"): 1,
    ("tab_dash.js", "vnChains", "3dfba995aa038f55"): 1,
    ("tab_other.js", "brokersBody", "301ab68d43ccff1e"): 1,
    ("tab_out.js", "exLink", "c094d874408e6338"): 1,
    ("tab_set.js", "sxIt", "42603d2b99d63229"): 1,
}


def _deep_sig(toks):
    return [[t.k, t.v if t.k != "tpl" else [list(t.q), [_deep_sig(ex) for ex in t.x or ()]]] for t in toks]


def _fn_key(toks, mb, ctxs, i):
    best = None
    for a, b, nm in ctxs:
        if a <= i <= b and (best is None or a > best[0]):
            best = (a, b, nm)
    if best is None:
        return None
    a, b, nm = best
    s0 = a
    if s0 and toks[s0 - 1].v == "=>":
        s0 -= 1
    if s0 and toks[s0 - 1].v == ")" and (s0 - 1) in mb:
        s0 = mb[s0 - 1]
    elif s0 and toks[s0 - 1].k == "name":
        s0 -= 1
    h = hashlib.sha1(json.dumps(_deep_sig(toks[s0:b + 1]), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return nm, h


def _has_safe_url(toks):
    for i, t in enumerate(toks):
        if t.k == "tpl" and any(_has_safe_url(ex) for ex in t.x or ()):
            return True
        if t.k == "name" and t.v == SAFE_URL_OBJ and i + 3 < len(toks) and toks[i + 1].v == "." and toks[i + 2].v == SAFE_URL_FN and toks[i + 3].v == "(" \
                and not (i and toks[i - 1].v in (".", "?.")):
            return True
    return False


def safe_url_sites(root):
    out = {}
    for unit, src in js_units(root):
        if unit != SUCC.TJDOM:
            seen = {}
            js_scan(unit, src, None, seen)
            out.update({(unit,) + k: v for k, v in seen.items()})
    return out


def _binds(toks, name):
    mb = match_brackets(toks)
    n, cnt, up, st = len(toks), 0, {}, []
    for i, t in enumerate(toks):
        if st:
            up[i] = st[-1]
        if t.k == "pun" and t.v in ("(", "{", "[") and i in mb:
            st.append(i)
        elif t.k == "pun" and t.v in (")", "}", "]") and st and mb.get(st[-1]) == i:
            st.pop()
    for i, t in enumerate(toks):
        if t.k == "tpl":
            cnt += sum(_binds(ex, name) for ex in t.x or ())
            continue
        if not (t.k == "name" and t.v == name) or (i and toks[i - 1].v in (".", "?.")):
            continue
        pv = toks[i - 1] if i else None
        nx = toks[i + 1].v if i + 1 < n else ""
        if (pv is not None and pv.k == "name" and pv.v in ("const", "let", "var", "function", "class")) or nx in ("=>", "=", "of", "in") \
                or nx.endswith("=") and nx not in ("==", "===", "!=", "!==", "<=", ">="):
            cnt += 1
            continue
        o = up.get(i)
        while o is not None:
            c = mb[o]
            after, before = (toks[c + 1].v if c + 1 < n else ""), (toks[o - 1].v if o else "")
            if (toks[o].v == "(" and (after in ("=>", "{") or before == "catch") and before not in ("if", "while", "for", "switch", "with")) \
                    or (toks[o].v in ("{", "[") and (before in ("const", "let", "var") or after == "=")):
                cnt += 1
                break
            o = up.get(o)
    return cnt


def _esc_one(src, tk0):
    defs = js_defs_all(src, ["esc"]).get("esc", [])
    return _binds(tk0, "esc") == 1 and ((len(defs) == 1 and defs[0].startswith("const ")) or (not defs and _borrows(src, "esc") == 1))


def _borrows(src, name):
    return int(any(name in [x.strip() for x in m.group(1).replace("\n", " ").split(",")] for m in re.finditer(r"const \{([^{}]*)\} = X;", src)))


def _flat_names(toks):
    out = []
    for i, t in enumerate(toks):
        if t.k == "tpl":
            for ex in t.x or ():
                out += _flat_names(ex)
        elif t.k == "name" and not (i and toks[i - 1].v in (".", "?.")):
            out.append(t.v)
    return out


def _tjdom_global_refs(toks):
    n = 0
    for i, t in enumerate(toks):
        if t.k == "tpl":
            n += sum(_tjdom_global_refs(ex) for ex in t.x or ()) + sum(q.strip() == SAFE_URL_OBJ for q in t.q or ())
        elif (t.k == "name" and t.v == SAFE_URL_OBJ and i and toks[i - 1].v in (".", "?.")) or (t.k == "str" and t.v.strip() == SAFE_URL_OBJ):
            n += 1
    return n


def _tjdom_member_only(toks):
    for i, t in enumerate(toks):
        if t.k == "tpl" and not all(_tjdom_member_only(ex) for ex in t.x or ()):
            return False
        if t.k == "name" and t.v == SAFE_URL_OBJ and not (i and toks[i - 1].v in (".", "?.")) \
                and not (i + 1 < len(toks) and toks[i + 1].k == "pun" and toks[i + 1].v == "."):
            return False
    return True


def js_census(root, node=None):
    counts, samples = {}, {}
    su_ok = safe_url_check(root, node)[0]
    for unit, src in js_units(root):
        tk0 = js_tokens(src)[0]
        sites = {k[1:]: v for k, v in SAFE_URL_SITES.items() if k[0] == unit} \
            if su_ok and unit != SUCC.TJDOM and _esc_one(src, tk0) else None
        for cat, fn, detail, line in js_scan(unit, src, sites):
            cat = _allow_cat(cat, unit, fn, detail)
            key = "%s::%s" % (unit, fn)
            counts.setdefault(cat, {})
            counts[cat][key] = counts[cat].get(key, 0) + 1
            samples.setdefault(cat, {}).setdefault(key, []).append("%s:%d %s" % (unit, line, detail.strip()))
    return counts, samples


def py_files(root, sub="src"):
    d = os.path.join(root, sub)
    if not os.path.isdir(d):
        return []
    out = []
    for dp, dn, fns in os.walk(d):
        dn[:] = sorted(x for x in dn if x != "__pycache__")
        for f in sorted(fns):
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return out


_PARSED = {}


def py_parse(path):
    if path not in _PARSED:
        with open(path, encoding="utf-8") as f:
            _PARSED[path] = ast.parse(f.read(), filename=path)
    return _PARSED[path]


def rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def call_name(node):
    f = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    elif isinstance(f, ast.Call):
        parts.append(call_name(f) + "()")
    else:
        return ""
    return ".".join(reversed(parts))


def str_consts(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def js_defs(src, names):
    toks, _ = js_tokens(src)
    mb = match_brackets(toks)
    out, n, want = {}, len(toks), set(names)
    for i, t in enumerate(toks):
        if not want:
            break
        if t.k == "name" and t.v in ("const", "let", "var") and i + 2 < n and toks[i + 1].k == "name" and toks[i + 1].v in want and toks[i + 2].v == "=":
            e = _expr_end(toks, i + 3, mb)
            end = toks[e].p if e < n else len(src)
            out[toks[i + 1].v] = src[t.p:end].rstrip() + ";"
            want.discard(toks[i + 1].v)
        elif t.k == "name" and t.v == "function" and i + 2 < n and toks[i + 1].k == "name" and toks[i + 1].v in want and toks[i + 2].v == "(" and (i + 2) in mb:
            b = mb[i + 2] + 1
            if b < n and toks[b].v == "{" and b in mb:
                out[toks[i + 1].v] = src[t.p:toks[mb[b]].p + 1]
                want.discard(toks[i + 1].v)
    return out


def called_names(toks, names):
    out = set()
    for i, t in enumerate(toks):
        if t.k == "tpl":
            for ex in t.x or ():
                out |= called_names(ex, names)
        if t.k == "name" and t.v in names and i + 1 < len(toks) and toks[i + 1].v == "(":
            pv = toks[i - 1] if i else None
            if not (pv is not None and pv.k == "pun" and pv.v in (".", "?.")) and not (pv is not None and pv.k == "name" and pv.v == "function"):
                out.add(t.v)
    return out


def js_defs_all(src, names, toks=None, out=None):
    toks = js_tokens(src)[0] if toks is None else toks
    out = {} if out is None else out
    mb = match_brackets(toks)
    n, want = len(toks), set(names)
    decl = set()
    for i, t in enumerate(toks):
        if t.k == "tpl":
            for ex in t.x or ():
                js_defs_all(src, names, ex, out)
        if t.k == "name" and t.v in want and i not in decl and i + 1 < n and toks[i + 1].k == "pun" and toks[i + 1].v in ("=", "||=", "??=", "&&=") \
                and not (i >= 1 and toks[i - 1].v in (".", "?.")):
            e = _expr_end(toks, i + 2, mb)
            end = toks[e].p if e < n else len(src)
            out.setdefault(t.v, []).append("let %s = %s;" % (t.v, src[toks[i + 2].p:end].rstrip()))
        if t.k == "name" and t.v in ("const", "let", "var"):
            j = i + 1
            while j < n and toks[j].k == "name":
                decl.add(j)
                if j + 1 < n and toks[j + 1].v == "=":
                    e = _expr_end(toks, j + 2, mb)
                    if toks[j].v in want:
                        end = toks[e].p if e < n else len(src)
                        out.setdefault(toks[j].v, []).append("%s %s = %s;" % (t.v, toks[j].v, src[toks[j + 2].p:end].rstrip()))
                else:
                    e = j + 1
                if e < n and toks[e].k == "pun" and toks[e].v == ",":
                    j = e + 1
                    continue
                break
        elif t.k == "name" and t.v == "function" and i + 2 < n and toks[i + 1].k == "name" and toks[i + 1].v in want and toks[i + 2].v == "(" and (i + 2) in mb:
            b = mb[i + 2] + 1
            if b < n and toks[b].v == "{" and b in mb:
                out.setdefault(toks[i + 1].v, []).append(src[t.p:toks[mb[b]].p + 1])
    return out


def escaper_defs(root):
    out = []
    for unit, src in js_units(root):
        used = called_names(js_tokens(src)[0], ESC_NAMES) | ({"esc"} if unit == SUCC.TJDOM else set())
        for nm, txts in sorted(js_defs_all(src, used).items()):
            for k, txt in enumerate(txts):
                out.append((unit, nm if k == 0 else "%s#%d" % (nm, k + 1), txt))
    return out


class _LazyMods:

    def __init__(self, ix):
        self.ix, self._t = ix, {}

    def get(self, name, default=None):
        if name in self._t:
            return self._t[name]
        p = self.ix._files.get(name)
        if p is None:
            return default
        try:
            self._t[name] = self.ix._table(py_parse(p))
        except SyntaxError:
            self._t[name] = None
        return self._t[name] if self._t[name] is not None else default

    def __getitem__(self, name):
        v = self.get(name)
        if v is None:
            raise KeyError(name)
        return v

    def __contains__(self, name):
        return name in self.ix._files

    def __iter__(self):
        return iter(list(self.ix.scan))

    def items(self):
        for n in self.ix.scan:
            v = self.get(n)
            if v is not None:
                yield n, v

    def __len__(self):
        return len(self.ix.scan)


class PyIndex:

    def __init__(self, root, subs=("src",), only=None):
        self.root, self._files, self.path, self.scan = root, {}, {}, []
        for sub in subs:
            for p in py_files(root, sub):
                r = rel(root, p)
                if r.startswith(("tools/refactor/", "tools/package/")):
                    continue
                name = os.path.splitext(os.path.basename(p))[0] if sub == "src" and "/brokers/" not in r else r
                self._files[name], self.path[name] = p, r
                if only is None:
                    self.scan.append(name)
                else:
                    with open(p, encoding="utf-8") as f:
                        if only(name, f.read()):
                            self.scan.append(name)
        self.mods = _LazyMods(self)

    @staticmethod
    def _table(tree):
        t = {"assign": {}, "imp": {}, "cls": {}, "func": {}, "tree": tree, "proxy": False}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tg in node.targets:
                    if isinstance(tg, ast.Name):
                        t["assign"][tg.id] = node.value
                    elif isinstance(tg, ast.Attribute) and tg.attr == "__class__" and isinstance(tg.value, ast.Subscript) \
                            and ast.unparse(tg.value) == "sys.modules[__name__]":
                        t["proxy"] = True
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                t["assign"][node.target.id] = node.value
            elif isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    t["imp"][a.asname or a.name] = (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    t["imp"][a.asname or a.name] = (a.name, None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                t["func"][node.name] = node
            elif isinstance(node, ast.ClassDef):
                attrs = {}
                for b in node.body:
                    if isinstance(b, ast.Assign):
                        for tg in b.targets:
                            if isinstance(tg, ast.Name):
                                attrs[tg.id] = b.value
                    elif isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        attrs.setdefault("__f__" + b.name, b)
                t["cls"][node.name] = attrs
        return t

    def _owner(self, mod, name, kind):
        m = self.mods.get(mod) or {}
        if not m.get("proxy") or name in m.get(kind, {}) or name in m.get("imp", {}):
            return mod
        for alias, (src_mod, src_name) in m.get("imp", {}).items():
            t2 = self.mods.get(src_mod) if src_name is None and alias == src_mod else None
            if t2 and name in t2.get(kind, {}):
                return src_mod
        return mod

    def _mod_attr(self, mod, name, depth):
        mod = self._owner(mod, name, "assign")
        m = self.mods.get(mod)
        if not m:
            return ""
        if name in m["assign"]:
            return self.resolve(mod, m["assign"][name], depth + 1)
        if name in m["imp"]:
            src_mod, src_name = m["imp"][name]
            if src_name:
                return self._mod_attr(src_mod, src_name, depth + 1)
        return ""

    def _self_attr(self, mod, name, depth):
        m = self.mods.get(mod)
        if not m:
            return ""
        for attrs in m["cls"].values():
            if name in attrs:
                return self.resolve(mod, attrs[name], depth + 1)
        for m2, t2 in self.mods.items():
            for attrs in t2["cls"].values():
                if name in attrs:
                    return self.resolve(m2, attrs[name], depth + 1)
        return ""

    def resolve(self, mod, node, depth=0):
        if depth > 12 or node is None:
            return ""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.resolve(mod, node.left, depth + 1) + self.resolve(mod, node.right, depth + 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            return re.sub(r"%[-#0 +]*\d*(?:\.\d+)?[sdifr]", "*", node.left.value)
        if isinstance(node, ast.Name):
            v = self._mod_attr(mod, node.id, depth)
            return v
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
                return self._self_attr(mod, node.attr, depth)
            if isinstance(node.value, ast.Name):
                m = self.mods.get(mod) or {}
                tgt = (m.get("imp") or {}).get(node.value.id)
                if tgt and tgt[1] is None:
                    return self._mod_attr(tgt[0], node.attr, depth)
                if node.value.id in self.mods:
                    return self._mod_attr(node.value.id, node.attr, depth)
            return ""
        if isinstance(node, ast.Call):
            fn = call_name(node)
            if fn in ("os.path.join", "path.join", "posixpath.join", "paths.state", "paths.StatePath"):
                if node.args:
                    last = self.resolve(mod, node.args[-1], depth + 1)
                    return last or "*"
            if fn in ("os.path.abspath", "os.path.realpath", "os.path.expanduser", "str"):
                return self.resolve(mod, node.args[0], depth + 1) if node.args else ""
            if fn in ("os.environ.get", "os.getenv") and len(node.args) > 1:
                return self.resolve(mod, node.args[1], depth + 1)
            f = None
            m = self.mods.get(mod) or {}
            if isinstance(node.func, ast.Name):
                f = (m.get("func") or {}).get(node.func.id)
                if f is None and node.func.id in (m.get("imp") or {}):
                    sm, sn = m["imp"][node.func.id]
                    f = ((self.mods.get(sm) or {}).get("func") or {}).get(sn)
                    mod = sm if f is not None else mod
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                tgt = (m.get("imp") or {}).get(node.func.value.id)
                mm = self._owner(tgt[0] if tgt and tgt[1] is None else node.func.value.id, node.func.attr, "func")
                f = ((self.mods.get(mm) or {}).get("func") or {}).get(node.func.attr)
                mod = mm if f is not None else mod
            if f is not None:
                rets = [n.value for n in ast.walk(f) if isinstance(n, ast.Return) and n.value is not None]
                if len(rets) == 1:
                    return self.resolve(mod, rets[0], depth + 1)
            return ""
        return ""

    def base(self, mod, node):
        s = self.resolve(mod, node)
        if not s:
            return ""
        return s.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


class FuncInfo:
    __slots__ = ("node", "qual", "nodes", "_la", "_li")

    def __init__(self, node, qual):
        self.node, self.qual, self.nodes, self._la, self._li = node, qual, [], None, None

    @property
    def imports(self):
        if self._li is None:
            li = {}
            for ch in self.nodes:
                if isinstance(ch, ast.ImportFrom) and ch.module:
                    for a9 in ch.names:
                        li[a9.asname or a9.name] = (ch.module, a9.name)
                elif isinstance(ch, ast.Import):
                    for a9 in ch.names:
                        li[a9.asname or a9.name] = (a9.name, None)
            self._li = li
        return self._li

    @property
    def assigns(self):
        if self._la is None:
            la = {}
            for ch in self.nodes:
                if isinstance(ch, ast.Assign):
                    for tg in ch.targets:
                        if isinstance(tg, ast.Name):
                            la.setdefault(tg.id, []).append(ch.value)
                        elif isinstance(tg, ast.Tuple) and isinstance(ch.value, ast.Tuple) and len(tg.elts) == len(ch.value.elts):
                            for a, b in zip(tg.elts, ch.value.elts):
                                if isinstance(a, ast.Name):
                                    la.setdefault(a.id, []).append(b)
                elif isinstance(ch, ast.AnnAssign) and isinstance(ch.target, ast.Name) and ch.value is not None:
                    la.setdefault(ch.target.id, []).append(ch.value)
                elif isinstance(ch, (ast.With, ast.AsyncWith)):
                    for it in ch.items:
                        if isinstance(it.optional_vars, ast.Name):
                            la.setdefault(it.optional_vars.id, []).append(it.context_expr)
            self._la = la
        return self._la


_FT = {}


def func_table(tree):
    key = id(tree)
    if key in _FT:
        return _FT[key]
    out = []

    def rec(node, cur, stack):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fi = FuncInfo(ch, ".".join(stack + [ch.name]))
                out.append(fi)
                rec(ch, fi, stack + [ch.name])
            elif isinstance(ch, ast.ClassDef):
                rec(ch, cur, stack + [ch.name])
            elif isinstance(ch, ast.Lambda):
                continue
            else:
                if cur is not None:
                    cur.nodes.append(ch)
                rec(ch, cur, stack)
    rec(tree, None, [])
    _FT[key] = out
    return out


def resolve_fi(ix, mod, fi, node, depth=0):
    if depth > 6:
        return ""
    if isinstance(node, ast.Name) and fi is not None:
        la = fi.assigns
        if node.id in la:
            for v in la[node.id]:
                r = resolve_fi(ix, mod, fi, v, depth + 1)
                if r:
                    return r
            return ""
        if node.id in fi.imports and fi.imports[node.id][1]:
            return ix._mod_attr(fi.imports[node.id][0], fi.imports[node.id][1], 0)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and fi is not None and node.value.id not in fi.assigns \
            and node.value.id in fi.imports and fi.imports[node.value.id][1] is None:
        return ix._mod_attr(fi.imports[node.value.id][0], node.attr, 0)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return resolve_fi(ix, mod, fi, node.left, depth + 1) + (resolve_fi(ix, mod, fi, node.right, depth + 1) or "*")
    if isinstance(node, ast.Call) and call_name(node) in ("os.path.join", "path.join", "paths.state", "paths.StatePath") and node.args:
        last = node.args[-1]
        r = resolve_fi(ix, mod, fi, last, depth + 1) if isinstance(last, (ast.Name, ast.BinOp, ast.Attribute)) else ix.resolve(mod, last)
        return r or "*"
    return ix.resolve(mod, node)


def _rpath(name):
    return os.path.join(BASE_DIR, "sec_%s.jsonl" % name)


def parse_rows(text):
    doc, rows = "", []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        if "_doc" in d and len(d) == 1:
            doc = d["_doc"]
        else:
            rows.append(d)
    return doc, rows


def load_rows(name):
    try:
        with open(_rpath(name), encoding="utf-8") as f:
            return parse_rows(f.read())
    except FileNotFoundError:
        return None


def save_rows(name, doc, rows, key):
    os.makedirs(BASE_DIR, exist_ok=True)
    out = [json.dumps({"_doc": doc}, ensure_ascii=False)] + [json.dumps(r, ensure_ascii=False) for r in sorted(rows, key=lambda r: r[key])]
    with open(_rpath(name), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def base_ref_rows(name):
    ref, top = base_ref()
    if not ref:
        return None, None, top
    relp = os.path.relpath(_rpath(name), top).replace(os.sep, "/")
    out = _git("show", "%s:%s" % (ref, relp))
    if out is None:
        return ref, None, "그 커밋에 표 없음(처음 생김)"
    try:
        return ref, parse_rows(out)[1], ""
    except (ValueError, KeyError):
        return ref, None, "그 커밋의 표를 못 읽음"


KW_ORDER = {"open": ("file", "mode"), "os.open": ("path", "flags", "mode"), "os.replace": ("src", "dst"), "os.rename": ("src", "dst"),
            "os.remove": ("path",), "os.unlink": ("path",), "shutil.copy2": ("src", "dst"), "shutil.copyfile": ("src", "dst"),
            "atomic_write_json": ("path",), "common.atomic_write_json": ("path",), "write_json_if_changed": ("path",),
            "common.write_json_if_changed": ("path",), "append_durable_jsonl": ("path",), "common.append_durable_jsonl": ("path",),
            "statefile.atomic_write_json": ("path",), "statefile.write_json_if_changed": ("path",), "statefile.append_durable_jsonl": ("path",),
            "_atomic_write_text": ("path", "text", "mode"), "ss._atomic_write_text": ("path", "text", "mode"),
            "settings_store._atomic_write_text": ("path", "text", "mode"), "fsio.atomic_write_text": ("path", "text")}


def kw_to_pos(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and n.keywords:
            order = KW_ORDER.get(call_name(n))
            if not order:
                continue
            kws = {k.arg: k for k in n.keywords if k.arg}
            for name in order[len(n.args):]:
                if name not in kws:
                    break
                n.args.append(kws[name].value)
                n.keywords.remove(kws[name])
    return tree


def module_fis(tree):
    main_ids = set()
    for st9 in tree.body:
        if isinstance(st9, ast.If) and "__main__" in ast.unparse(st9.test):
            main_ids |= {id(x) for x in ast.walk(st9)}
    out, mn = [], module_nodes(tree)
    for q9, keep in (("<mod>", lambda n: id(n) not in main_ids), ("<main>", lambda n: id(n) in main_ids)):
        fi = FuncInfo(tree, q9)
        fi.nodes = [n for n in mn if keep(n)]
        if fi.nodes:
            out.append(fi)
    return out


def module_nodes(tree):
    owned = set()
    for fi in func_table(tree):
        owned.update(id(n) for n in fi.nodes)
        owned.add(id(fi.node))
    out = []
    for n in ast.walk(tree):
        if id(n) not in owned and not isinstance(n, ast.Module):
            out.append(n)
    return out
