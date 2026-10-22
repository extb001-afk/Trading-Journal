import ast
import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _arch_py_defs as D  # noqa: E402
import _arch_py_ratchet as R  # noqa: E402

K = "money.gwrite"
FILE = "money_gwrite.jsonl"
KEYS = ("qty_known", "qty_unknown", "cost", "realized")
TL = "qty_timeline"
TL_METH = ("append", "extend", "insert")
ALLOW_KIND = "gwrite"
REASONS = {
    "flow": "사이클 flow dict(flow_of 결과 · g['cur'] · g['flows'] 원소 — 그룹 칸이 아니라 사이클 칸)",
    "transit": "트랜짓·보낸 내역 항목(fx_transit·fxdep_transit·rt_transit·ret_pool·보낸 토큰·풀)",
    "sale": "세일 링크·로트 사용·지급 항목(sale_links·sale_used·로트 _pay)",
    "agg": "집계 dict(가스 무시세·무처리 묶음 등 그룹 밖 합계)",
    "lp": "LP 장부 항목(LpBook 의 풀 칸)",
    "view": "화면 행·링크 dict(pendings·outflows·view_misc — 원가 상태 아님)",
}
_ORDER = ("k", "m", "q", "f", "h", "b", "s", "v", "c")


def const_key(sub):
    sl = sub.slice
    if hasattr(ast, "Index") and isinstance(sl, getattr(ast, "Index")):
        sl = sl.value
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


def unparse(node):
    return ast.unparse(node)


class _Scan(ast.NodeVisitor):

    def __init__(self):
        self.qual, self.fpath, self.rows, self.memo = [], [], [], {}
        self.fn_info = [[D.MODULE_Q, None, None, None]]
        self.scopes = [self.fn_info[0]]

    def _func(self, n):
        self.qual.append(n.name)
        self.fpath.append(n.name)
        q, f = ".".join(self.qual), ".".join(self.fpath)
        self.fn_info.append([q, f if f != q else None, None, n])
        self.scopes.append(self.fn_info[-1])
        self.generic_visit(n)
        self.fn_info.pop()
        self.fpath.pop()
        self.qual.pop()

    def visit_ClassDef(self, n):
        self.qual.append(n.name)
        self.fn_info.append([".".join(self.qual) + D.BODY_SUFFIX, None, None, None])
        self.scopes.append(self.fn_info[-1])
        self.generic_visit(n)
        self.fn_info.pop()
        self.qual.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _func

    def _rec(self, n, kind, sub, key):
        info = self.fn_info[-1]
        if info[3] is not None and info[2] is None:
            info[2] = D.fingerprint(info[3], self.memo)
        q, f, h = info[:3]
        self.rows.append({"l": n.lineno, "q": q, "f": f, "h": h,
                          "b": unparse(sub.value), "s": key, "kind": kind})

    def _target(self, n, t, kind):
        if isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self._target(n, e, kind)
        elif isinstance(t, ast.Starred):
            self._target(n, t.value, kind)
        elif isinstance(t, ast.Subscript):
            k = const_key(t)
            if k in KEYS or k == TL:
                self._rec(n, kind, t, k)

    def visit_Assign(self, n):
        for t in n.targets:
            self._target(n, t, "set")
        self.generic_visit(n)

    def visit_AnnAssign(self, n):
        if n.value is not None:
            self._target(n, n.target, "set")
        self.generic_visit(n)

    def visit_AugAssign(self, n):
        self._target(n, n.target, "aug" + type(n.op).__name__)
        self.generic_visit(n)

    def visit_Delete(self, n):
        for t in n.targets:
            self._target(n, t, "del")
        self.generic_visit(n)

    def visit_For(self, n):
        self._target(n, n.target, "for")
        self.generic_visit(n)

    visit_AsyncFor = visit_For

    def visit_With(self, n):
        for it in n.items:
            if it.optional_vars is not None:
                self._target(n, it.optional_vars, "with")
        self.generic_visit(n)

    visit_AsyncWith = visit_With

    def visit_comprehension(self, n):
        self._target(n.target, n.target, "comp")
        self.generic_visit(n)

    def visit_Call(self, n):
        fn = n.func
        if isinstance(fn, ast.Attribute) and fn.attr in TL_METH and isinstance(fn.value, ast.Subscript) \
                and const_key(fn.value) == TL:
            self._rec(n, "call." + fn.attr, fn.value, TL)
        self.generic_visit(n)


def scan_text(text, name="<src>", scopes=None):
    v = _Scan()
    v.visit(ast.parse(text, name))
    if scopes is not None:
        for info in v.scopes:
            if info[3] is not None and info[2] is None:
                info[2] = D.fingerprint(info[3], v.memo)
            scopes.append({"q": info[0], "f": info[1], "h": info[2], "t": _type(info[0]), "v": 0})
    return v.rows


def matches(mod, patterns):
    for p in patterns:
        if (p.endswith("*") and mod.startswith(p[:-1])) or mod == p:
            return True
    return False


def counted_modules(rules, available):
    allow = (rules.get("api_allow") or {}).get(ALLOW_KIND, [])
    return sorted(m for m in set(rules.get("money_modules", [])) & set(available) if not matches(m, allow))


def src_modules(src):
    return {n[:-3]: os.path.join(src, n) for n in sorted(os.listdir(src)) if n.endswith(".py")}


def survey(src, rules):
    out, scopes, errors = [], [], []
    paths = src_modules(src)
    counted = set(counted_modules(rules, paths))
    for m in sorted(paths):
        sc = []
        try:
            with open(paths[m], encoding="utf-8") as f:
                rows = scan_text(f.read(), paths[m], sc)
        except (OSError, UnicodeDecodeError, SyntaxError) as e:
            errors.append("%s: %s" % (m, e))
            continue
        for r in rows if m in counted else ():
            r["m"] = m
            out.append(r)
        for u in sc:
            u["m"] = m
            scopes.append(u)
    return out, scopes, errors


def sites(src, rules):
    rows, _scopes, errors = survey(src, rules)
    return rows, errors


def bundles(rows):
    acc = {}
    for r in rows:
        key = (r["m"], r["q"], r["b"], r["s"])
        u = acc.get(key)
        if u is None:
            u = acc[key] = {"k": K, "m": r["m"], "q": r["q"], "f": r["f"], "h": r["h"], "b": r["b"], "s": r["s"], "v": 0,
                            "t": _type(r["q"]), "at": "src/%s.py:%d" % (r["m"], r["l"])}
        u["v"] += 1
    return [acc[k] for k in sorted(acc)]


def _type(q):
    if q == D.MODULE_Q:
        return "m"
    return "b" if q.endswith(D.BODY_SUFFIX) else "f"


def reason_ok(c):
    return c == "group" or (isinstance(c, str) and c.startswith("other:") and c[6:] in REASONS)


def parse(text, where):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = R.loads(line)
        except ValueError as e:
            raise ValueError("%s:%d JSON 이 아님(%s)" % (where, n, e))
        bad = not isinstance(d, dict) or d.get("k") != K or any(not isinstance(d.get(x), str) or not d.get(x)
                                                                for x in ("m", "q", "b", "s"))
        bad = bad or d.get("s") not in KEYS + (TL,) or not R.valid_value("func.lines", d.get("v")) or d.get("v") < 1
        if bad or not reason_ok(d.get("c")):
            raise ValueError("%s:%d 줄 모양 틀림(k=%s · m·q·b·s 글자 · s 열쇠 · v ≥ 1 정수 · c = group|other:<%s>) %s" % (
                where, n, K, "|".join(sorted(REASONS)), line[:160]))
        d["t"] = _type(d["q"])
        out.append(d)
    return out


def load(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return parse(f.read(), path)


def identity(u):
    return {x: u[x] for x in _ORDER if u.get(x) not in (None, "")}


def dump(path, lines):
    rows = sorted((identity(d) for d in lines), key=lambda d: tuple(json.dumps(d.get(x), ensure_ascii=False) for x in _ORDER))
    text = "".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n" for d in rows)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_gw_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _funcs(items):
    out, at = [], {}
    for u in items:
        key = (u["m"], u["q"])
        i = at.get(key)
        if i is None:
            i = at[key] = len(out)
            out.append({"m": u["m"], "q": u["q"], "f": u.get("f"), "h": u.get("h"), "t": u["t"], "v": 0})
        out[i]["v"] += u["v"]
    return out, at


def func_map(base, cur, scopes=()):
    bf, _ = _funcs(base)
    cf, _ = _funcs(list(cur) + list(scopes))
    return {(cf[j]["m"], cf[j]["q"]): (bf[i]["m"], bf[i]["q"]) for i, j in R.match(bf, cf).items()}


class Verdict:

    def __init__(self):
        self.new, self.grew, self.stale, self.pairs, self.moved = [], [], [], {}, 0

    @property
    def ok(self):
        return not self.new and not self.grew


def compare(cur, base, scopes=()):
    vd = Verdict()
    fm = func_map(base, cur, scopes)
    by_id = {(b["m"], b["q"], b["b"], b["s"]): i for i, b in enumerate(base)}
    for j, u in enumerate(cur):
        fq = fm.get((u["m"], u["q"]))
        i = by_id.get(fq + (u["b"], u["s"])) if fq else None
        if i is None or i in vd.pairs.values():
            vd.new.append(u)
            continue
        vd.pairs[j] = i
        if fq != (u["m"], u["q"]):
            vd.moved += 1
        if u["v"] > base[i]["v"]:
            vd.grew.append((u, base[i]))
    back = {i: j for j, i in vd.pairs.items()}
    for i, b in enumerate(base):
        j = back.get(i)
        if j is None or cur[j]["v"] < b["v"] or (cur[j]["m"], cur[j]["q"]) != (b["m"], b["q"]):
            vd.stale.append((cur[j] if j is not None else None, b))
    return vd


def classified(cur, base, vd):
    return [base[vd.pairs[j]]["c"] if j in vd.pairs else None for j in range(len(cur))]


def loosened(new, old, cur, scopes=()):
    fm = func_map(old, cur, scopes)
    by_id = {(b["m"], b["q"], b["b"], b["s"]): i for i, b in enumerate(old)}
    live = {(u["m"], u["q"]): (u.get("f"), u.get("h")) for u in list(scopes) + list(cur)}
    used, out = set(), []
    for u in new:
        i = by_id.get((u["m"], u["q"], u["b"], u["s"]))
        if i is None or i in used:
            fq = fm.get((u["m"], u["q"]))
            i = by_id.get(fq + (u["b"], u["s"])) if fq else None
        if i is None or i in used:
            out.append("새 줄 %s %s %s[%r] = %d %s" % (u["m"], u["q"], u["b"], u["s"], u["v"], u["c"]))
            continue
        used.add(i)
        fh = (u.get("f"), u.get("h"))
        if fh != (old[i].get("f"), old[i].get("h")) and fh != live.get((u["m"], u["q"])):
            out.append("지문·경로 바뀜(기준점 줄과도 지금 소스와도 다름) %s %s %s[%r] %s → %s" % (
                u["m"], u["q"], u["b"], u["s"], (old[i].get("f"), old[i].get("h")), fh))
        if u["v"] > old[i]["v"]:
            out.append("커짐 %s %s %s[%r] %d → %d" % (u["m"], u["q"], u["b"], u["s"], old[i]["v"], u["v"]))
        if u["c"] != old[i]["c"]:
            out.append("분류 바뀜 %s %s %s[%r] %s → %s" % (u["m"], u["q"], u["b"], u["s"], old[i]["c"], u["c"]))
    return out


def tighten(cur, base, scopes=()):
    vd = compare(cur, base, scopes)
    if not vd.ok:
        return None, vd
    lines = [dict(identity(cur[j]), c=base[i]["c"]) for j, i in sorted(vd.pairs.items())]
    return lines, vd


def freeze(cur, base, table, scopes=()):
    vd = compare(cur, base or [], scopes)
    want = {(t["m"], t["q"], t["b"], t["s"]): t["c"] for t in table}
    lines, missing = [], []
    for j, u in enumerate(cur):
        c = want.get((u["m"], u["q"], u["b"], u["s"])) or (base[vd.pairs[j]]["c"] if j in vd.pairs else None)
        if not reason_ok(c):
            missing.append("%s %s %s[%r] (분류 %r)" % (u["m"], u["q"], u["b"], u["s"], c))
            continue
        lines.append(dict(identity(u), c=c))
    return lines, missing


def summary(rows, cur, cls):
    by_key = {k: 0 for k in KEYS + (TL,)}
    for r in rows:
        by_key[r["s"]] += 1
    by_c = {}
    for u, c in zip(cur, cls):
        name = "group" if c == "group" else ("other" if c else "?")
        n_b, n_s = by_c.get(name, (0, 0))
        by_c[name] = (n_b + 1, n_s + u["v"])
    return by_key, by_c


def _paths():
    root = os.path.realpath(os.path.join(HERE, "..", ".."))
    return os.path.join(root, "src"), os.path.join(HERE, "arch_baseline", "py_rules.json"), os.path.join(HERE, "arch_baseline", FILE)


def main(argv):
    src, rules_path, base_path = _paths()
    if not os.path.isfile(rules_path):
        print("규칙 파일 없음 — 저장소 배치에서 쓰는 명령")
        return 1
    with open(rules_path, encoding="utf-8") as f:
        rules = R.loads(f.read())
    rows, scopes, errors = survey(src, rules)
    if errors and ("--update-lower" in argv or "--freeze" in argv):
        print("기준선 갱신 거부 — 소스 분석 실패: " + " · ".join(errors))
        return 1
    cur = bundles(rows)
    base = load(base_path)
    if "--update-lower" in argv:
        if base is None:
            print("기준선 없음 — 총괄이 --freeze <분류표>로 처음 만든다")
            return 1
        lines, vd = tighten(cur, base, scopes)
        if lines is None:
            print("거부(새 묶음 %d · 커짐 %d — 코드를 고치거나 총괄이 --freeze)" % (len(vd.new), len(vd.grew)))
            return 1
        if [identity(x) for x in lines] != [identity(x) for x in base] or vd.stale:
            dump(base_path, lines)
            print("조임 %d → %d줄(옮김 %d)" % (len(base), len(lines), vd.moved))
        else:
            print("바뀐 것 없음")
        return 0
    if "--freeze" in argv:
        i = argv.index("--freeze")
        table = []
        if i + 1 < len(argv):
            with open(argv[i + 1], encoding="utf-8") as f:
                table = R.loads(f.read())
        lines, missing = freeze(cur, base, table, scopes)
        if missing:
            print("거부 — 분류 없는 묶음 %d:\n  %s" % (len(missing), "\n  ".join(missing)))
            return 1
        dump(base_path, lines)
        print("기준선 씀 %d줄(%s)" % (len(lines), base_path))
        return 0
    vd = compare(cur, base or [], scopes)
    cls = classified(cur, base or [], vd)
    for j, (u, c) in enumerate(zip(cur, cls)):
        b = base[vd.pairs[j]]["v"] if j in vd.pairs else "-"
        print("%-12s %3d (기준선 %s) %s %s %s[%r]" % (c or "?", u["v"], b, u["m"], u["q"], u["b"], u["s"]))
    by_key, by_c = summary(rows, cur, cls)
    print("열쇠별 문장 %s · 합 %d · 묶음 %d · 분류별(묶음, 문장) %s" % (by_key, len(rows), len(cur), by_c))
    print("새 %d · 커짐 %d · 낮출 수 있음 %d · 옮김 %d" % (len(vd.new), len(vd.grew), len(vd.stale), vd.moved))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
